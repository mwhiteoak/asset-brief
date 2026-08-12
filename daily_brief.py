"""
The Asset Brief — daily Australian commercial property intelligence email.

Pipeline (each weekday morning):
  1. ASX feed      — price-sensitive announcements pulled directly from the
                     ASX API for every ticker in config.yml.
  2. Research pass — four parallel Claude calls, each with web search HARD-
                     RESTRICTED to the approved domain allowlist, covering
                     (a) capital markets, (b) occupiers/leasing/people,
                     (c) alternatives + proptech, (d) operations, compliance
                     and centre marketing. Output: structured findings, each
                     scored 0-10 for relevance to the reader.
  2b. Relevance gate — findings below config.yml's min_relevance are dropped
                     before the editor sees them, and logged so it can be tuned.
  3. Editor pass   — one Claude call that gets the findings, the ASX items,
                     the watchlist, the last 14 days of headlines (dedup) and
                     the open-deal tracker, then writes the edition and a
                     machine-readable deal log.
  4. Extras        — market signals strip (RBA/Yahoo), optional Grok shitpost.
  5. Send + persist — Gmail SMTP; edition archived to docs/, deal log
                     appended to data/memory.json, both committed by the
                     workflow.

Env vars: ANTHROPIC_API_KEY, GMAIL_ADDRESS, GMAIL_APP_PASSWORD required;
RECIPIENT_EMAIL, XAI_API_KEY, DRY_RUN optional.
"""

import concurrent.futures
import json
import os
import re
import smtplib
import sys
import threading
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
# Imported by name: `html` is used as a local variable for the rendered email
# throughout this module, so importing the module itself would shadow it.
from html import escape as html_escape, unescape as html_unescape
from zoneinfo import ZoneInfo

import anthropic
import requests
import yaml
from dotenv import load_dotenv

import asx_feed
import asx_insights
import brief_memory
import forward_calendar
import grok_research
import market_signals
import portfolio_trends

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
ROOT = os.path.dirname(os.path.abspath(__file__))
# Local dev convenience: load .env if present. In GitHub Actions the secrets
# are already in the environment, and real env vars always win over the file.
load_dotenv(os.path.join(ROOT, ".env"))

with open(os.path.join(ROOT, "config.yml")) as f:
    CONFIG = yaml.safe_load(f)

BRIEF_NAME = "The Asset Brief"
# Recipients live in the RECIPIENT_EMAIL secret (comma-separated) so no real
# address sits in source. All recipients are BCC'd, so addresses stay private
# from each other. Falls back to GMAIL_ADDRESS — i.e. send to yourself.
TIMEZONE = ZoneInfo("Australia/Brisbane")
DEAL_THRESHOLD = "$5 million"

# The research pass is high-volume search-and-extract work — Sonnet handles it
# well and it's where most of the token spend goes. The editor pass is the one
# call that exercises real judgement (what leads, what's a repeat, what a
# tracked deal moving actually means), so it gets Opus.
RESEARCH_MODEL = "claude-sonnet-5"
EDITOR_MODEL = "claude-opus-5"
# Each search compounds the turn's context (the server-side loop resends
# accumulated results), so this drives cost far more than it looks. Measured
# at ~420k input tokens per cluster at 12; ~8 is the sensible balance between
# coverage and spend. Watch the COST line at the end of a run before raising.
# Lowered from 8 once Grok became the primary source: the Anthropic clusters
# now add allowlist-guaranteed trade-press depth rather than carrying the
# edition, so they don't need to search as widely.
SEARCHES_PER_CLUSTER = 5

# USD per million tokens, for the run-cost estimate only.
PRICING = {
    "claude-sonnet-5": (3.00, 15.00),
    "claude-opus-5": (5.00, 25.00),
}
# Hard ceiling on the whole parallel research phase. Streaming responses never
# trip a per-request timeout while data is trickling, so this is what actually
# keeps the run inside the workflow budget.
RESEARCH_DEADLINE_S = 900

MIN_RELEVANCE = int(CONFIG.get("min_relevance", 5))
# Hard recency ceiling, enforced in code. The research window is 48-76 hours;
# this allows for search-index lag without letting genuinely old stories in.
MAX_FINDING_AGE_DAYS = int(CONFIG.get("max_finding_age_days", 7))

GEOGRAPHY = (
    "Australia-wide, with strongest emphasis on Queensland and New South Wales. "
    "Always include significant national deals but lead QLD/NSW where possible."
)

# Who actually reads this. Every scoring decision hangs off these five jobs —
# the test for any story is "does this change what this team does this week?"
AUDIENCE = """This brief is read at two levels inside a private Australian property group,
and it must serve both in a single email.

EXECUTIVE (CEO / COO) — they decide capital allocation and carry the risk:
  - CAPITAL AND FUNDING — cost of debt, credit spreads, bank and non-bank
    appetite, refinancing conditions, where institutional and offshore money
    is rotating into or out of.
  - VALUATION DIRECTION — cap rate movement with evidence, what the latest
    prints do to the carrying value of a book like theirs.
  - COMPETITIVE POSITION — what peer groups and institutions are doing
    strategically: fund launches, capital raisings, portfolio rotation,
    mandate shifts, entries and exits.
  - STRUCTURAL RISK AND POLICY — planning, tax, foreign investment, ESG
    mandates and regulation that reshape the operating model or the cost base.

OPERATIONAL (asset management team) — they run the assets day to day:
  - PROPERTY MANAGEMENT — tenant health, arrears, outgoings, rent reviews,
    holding centres and buildings full and performing.
  - LEASING — deals, incentives, rents, expiries, tenant demand and who is
    expanding or contracting in their formats and catchments.
  - MARKETING — centre campaigns, foot traffic, tenant-mix and brand news
    that affects how an asset is positioned.
  - ACQUISITIONS AND DISPOSALS — what is trading, at what price and yield,
    who is buying and selling, what is coming to market.
  - FACILITIES MANAGEMENT — building services, compliance, ESG and NABERS
    obligations, essential-services and safety regulation, major capex.

An item can be high value to one level and noise to the other. Score for the
HIGHER of the two — a debt-market shift a CEO must act on still belongs in
the brief even if it changes nothing for a centre manager this week."""

# The gate that keeps the brief from becoming a press-release feed.
RELEVANCE_RUBRIC = """Score every finding 0-10 for how much it changes a decision at EITHER level.
  9-10  Changes a decision now. A tenant of theirs — or any national retailer
        with a store network — entering administration, closing stores or
        expanding; a comparable asset trading in their markets with price AND
        yield; a debt-cost or credit-availability shift that moves the cost of
        capital; a regulatory change with a compliance deadline and a cost.
  7-8   Strong signal. Cap rate or valuation movement with evidence; a major
        occupier's national network plan; a peer group's fund launch, capital
        raising or portfolio rotation; institutional or offshore capital
        entering or exiting a sector; ESG/essential-services rules starting to
        bite; a leasing deal that sets a rent or incentive benchmark.
  5-6   Useful context. A significant national transaction outside their
        markets; a sector-wide leasing, funding or construction-cost trend
        carrying real numbers.
  3-4   Peripheral. Corporate news with no read-through to a building, a
        balance sheet or a strategy; people moves outside their patch.
  0-2   Noise. Share price commentary, opinion pieces, awards, sponsored
        content, PR with no figures, residential-only news, anything already
        obvious to someone in the industry.

CALIBRATION NOTES — these have been mis-scored before, so be deliberate:
  - A retailer collapsing into administration is a 7 or higher, ALWAYS, even
    if none of their centres is named. Store networks are a landlord's risk
    register, and a brand in administration is a covenant event somewhere.
  - An operator's margin compression (wage costs, funding changes, subsidy
    shifts) in childcare or aged care is a 6-7: it is tenant covenant risk,
    not general industry news.
  - A transaction with BOTH a price and a yield is at least a 7 — it is a
    comparable, and comparables are the scarcest thing in this brief.
  - Debt markets, credit spreads and refinancing conditions score 7+ even
    with no property named. That is the CEO's core input.

Score honestly and strictly — a story you cannot write a concrete "so what"
line for is a 4 or below.

But DO NOT use the score to decide what to return. Return EVERY genuine
finding you come across, including the ones you scored 2 or 3. A separate
filter downstream drops the low scorers, and the dropped items are logged so
the threshold can be tuned. Your job here is coverage and honest scoring, not
filtering — an item you silently omit is invisible, whereas a low-scored one
costs nothing. Returning an empty list should happen only when your searches
genuinely surfaced nothing at all."""

RESEARCH_CLUSTERS = {
    "capital_markets": (
        "Transactions and capital markets across retail, commercial office, "
        "industrial, childcare and aged care property: sales, acquisitions, "
        "disposals, portfolios hitting the market, campaign launches, letters "
        "of intent, heads of agreement, assets in due diligence, fund "
        "launches and capital raisings. Capture price, yield/cap rate, "
        "vendor, purchaser and agents whenever reported. Minimum deal size "
        f"{DEAL_THRESHOLD} (childcare/aged care may be smaller if notable)."
    ),
    "occupiers_people": (
        "Occupier and people news: lease deals, pre-commitments, renewals, "
        "incentive and rent signals across office, retail and industrial; "
        "retailer expansions, closures and administrations; industrial "
        "occupier demand; office tenant relocations; and people moves — "
        "appointments and departures across agencies, fund managers, "
        "institutions and boards (AICD announcements count)."
    ),
    "alternatives_proptech": (
        "Alternatives and proptech: childcare and aged care operator news, "
        "auction results, cap rate signals, funding and regulatory changes "
        "(CCS, ACQSC etc.); plus proptech raises, launches and adoption "
        "stories relevant to asset and property management."
    ),
}
# NOTE: an "operations_compliance" Anthropic cluster used to live here. It was
# removed after two consecutive runs where it returned 13 findings, ALL of them
# stale (up to 203 days old) and several drifting off-brief into transactions.
# Compliance and ESG have thin recent trade-press coverage, so it reached
# backwards to fill the quota. Those topics are now covered by the Grok pass,
# which reads the mastheads and dates its findings reliably.


_USAGE: list[tuple[str, int, int]] = []
_USAGE_LOCK = threading.Lock()


def track(model: str, response) -> None:
    """Record a call's token usage so the run can report what it actually cost."""
    u = getattr(response, "usage", None)
    if u is None:
        return
    with _USAGE_LOCK:
        _USAGE.append((model, getattr(u, "input_tokens", 0) or 0,
                       getattr(u, "output_tokens", 0) or 0))


def report_cost() -> None:
    if not _USAGE:
        return
    total = 0.0
    by_model: dict[str, list[int]] = {}
    for model, tin, tout in _USAGE:
        agg = by_model.setdefault(model, [0, 0, 0])
        agg[0] += tin
        agg[1] += tout
        agg[2] += 1
    for model, (tin, tout, calls) in by_model.items():
        pin, pout = PRICING.get(model, (0.0, 0.0))
        cost = tin / 1e6 * pin + tout / 1e6 * pout
        total += cost
        print(f"COST  {model}: {calls} calls, {tin:,} in / {tout:,} out "
              f"= ${cost:.2f}")
    print(f"COST  total this run: ${total:.2f}  "
          f"(~${total * 21:.0f}/month at 21 editions)")


def date_window():
    now = datetime.now(TIMEZONE)
    if now.weekday() == 0:  # Monday — weekend wrap
        start = now - timedelta(days=3)
        label = f"Weekend Wrap — {now.strftime('%A %d %B %Y')}"
        window = (
            f"from {start.strftime('%A %d %B')} through this morning "
            f"({now.strftime('%A %d %B %Y')}) Brisbane time"
        )
        lookback_hours = 76
    else:
        start = now - timedelta(days=2)
        label = now.strftime("%A %d %B %Y")
        window = (
            f"the last 48 hours ({start.strftime('%A %d %B')} to "
            f"{now.strftime('%A %d %B %Y')}) Brisbane time"
        )
        lookback_hours = 52
    return now, label, window, lookback_hours


# ----------------------------------------------------------------------------
# Pass 1 — research (allowlist-enforced web search)
# ----------------------------------------------------------------------------
def research_cluster(client, name: str, focus: str, window: str) -> list[dict]:
    prompt = f"""You are a research analyst for "{BRIEF_NAME}", a daily brief for the
Head of Asset Management at a private Australian property group.

WHO YOU ARE WRITING FOR:
{AUDIENCE}

RECENCY IS A HARD REQUIREMENT. Only report news published within {window}.
Nothing older qualifies, no matter how relevant it looks — an old deal
presented as current is the single worst failure this brief can make, because
the reader prices real assets off these comparables.

Agency and trade-press pages are frequently YEARS old while still ranking well
in search, and many carry no visible date. Before returning ANY finding you
must try to establish its actual publication date from the page itself. Put it
in "date_iso" as YYYY-MM-DD. Never guess it, never infer it from a search
result's position, never assume a page is recent because it surfaced in a
search, and NEVER substitute today's date.

If you genuinely cannot establish the date, still RETURN the finding with
"date_iso": null. A downstream filter rejects undated and out-of-window items
and logs them, so returning it costs nothing and lets the threshold be tuned —
whereas silently dropping it makes the loss invisible. Report and date; let
the filter decide.

FOCUS AREA: {focus}

Geography: {GEOGRAPHY}

RELEVANCE SCORING — apply this to every finding before you return it:
{RELEVANCE_RUBRIC}

Your web search is technically restricted to an approved allowlist of
reputable outlets — trade press, major mastheads, industry bodies, agency
press rooms and the ASX. Work within it; do not attempt to reference
anything outside it.

WATCHLIST — findings involving any of these are top priority, tag them
"watchlist": {json.dumps(CONFIG.get("watchlist", {}))}

Output ONLY a JSON array between <FINDINGS> and </FINDINGS>. Each element:
{{
  "headline": "...",
  "summary": "2-3 sentences with the concrete facts — price, yield, parties,
              agents, sqm, terms — whatever was reported",
  "url": "the real article URL from your search results",
  "source": "publication name",
  "date_iso": "YYYY-MM-DD — the article's ACTUAL publication date, verified
               from the page. Omit the finding entirely if you cannot
               establish this. Never substitute today's date.",
  "sector": "retail|office|industrial|childcare|aged_care|proptech|other",
  "state": "QLD|NSW|VIC|WA|SA|ACT|TAS|NT|national",
  "discipline": "property_management|leasing|marketing|transactions|
                 facilities_management" (which of the reader's jobs it lands on),
  "relevance": 0-10 per the rubric above,
  "so_what": "one concrete sentence on what this means for the reader — if you
              cannot write one without padding, the score is 4 or below",
  "tags": ["watchlist" if applicable, "transaction"/"leasing"/"tenant"/
           "people"/"regulatory" etc.]
}}
Rules: every finding MUST have a real URL from your searches — no URL, no
finding. Do not fabricate or reconstruct URLs. Do NOT inflate relevance to
make a finding survive, and do NOT omit findings because you scored them low
— return them and let the downstream filter do its job. No text outside the
markers."""

    messages = [{"role": "user", "content": prompt}]

    def search_tool(domains):
        return [{
            # Deliberately the BASIC variant, not web_search_20260209.
            # Dynamic filtering wraps each query in server-side code execution
            # that fires many underlying searches per logical query — measured
            # at 25 tool calls against a max_uses of 8, which exhausted the
            # budget, spent the rest of the turn erroring, and returned zero
            # findings. It also pulled ~187k input tokens for a single cluster
            # and pushed the research phase past 17 minutes. For a daily job
            # on a fixed budget the basic tool is the right trade.
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": SEARCHES_PER_CLUSTER,
            "allowed_domains": domains,
        }]

    domains = list(CONFIG["allowed_domains"])
    text = ""
    for _ in range(4):
        try:
            # Streamed: a search-and-extract turn can run for minutes, and a
            # non-streaming call that stalls burns the SDK's 10-minute timeout
            # (times retries) against the workflow's budget.
            with client.messages.stream(
                model=RESEARCH_MODEL,
                max_tokens=10000,
                messages=messages,
                tools=search_tool(domains),
            ) as stream:
                response = stream.get_final_message()
            track(RESEARCH_MODEL, response)
        except anthropic.BadRequestError as e:
            # A publisher blocking Anthropic's crawler makes the API reject the
            # WHOLE request, so one bad domain would otherwise cost us the
            # entire cluster. Drop the named domains and try again.
            blocked = set(re.findall(r"'([^']+\.[^']+)'", str(e)))
            remaining = [d for d in domains if d not in blocked]
            if not blocked or len(remaining) == len(domains) or not remaining:
                raise
            print(f"[warn] cluster {name}: dropping domains blocked to the "
                  f"crawler — remove these from config.yml: "
                  f"{sorted(blocked)}", file=sys.stderr)
            domains = remaining
            continue

        text = "\n".join(b.text for b in response.content if b.type == "text")
        # The server-side search loop can stop early with pause_turn on a long
        # run. Resume rather than silently returning an empty cluster.
        if response.stop_reason != "pause_turn":
            break
        print(f"[info] cluster {name}: pause_turn — resuming search")
        messages = messages[:1] + [
            {"role": "assistant", "content": response.content}
        ]

    m = re.search(r"<FINDINGS>(.*?)</FINDINGS>", text, re.DOTALL)
    if not m:
        print(f"[warn] cluster {name}: no FINDINGS markers", file=sys.stderr)
        return []
    try:
        findings = json.loads(m.group(1).strip())
    except json.JSONDecodeError as e:
        print(f"[warn] cluster {name}: bad JSON ({e})", file=sys.stderr)
        return []
    if not isinstance(findings, list):
        return []

    return gate_findings(name, findings)


def gate_findings(name: str, findings: list) -> list[dict]:
    """Recency + relevance gate. Every research source goes through this.

    Grok gets no more trust than Anthropic does: same date validation, same
    threshold, same logging. Keeping this in one function is what guarantees
    that stays true as sources are added.
    """
    kept, dropped, stale = [], [], []
    today = datetime.now(TIMEZONE).date()
    for f in findings:
        if not isinstance(f, dict) or not f.get("url"):
            continue

        # Recency is enforced here, not just asked for in the prompt. Agency
        # and trade-press pages rank well for years and often carry no visible
        # date; an old comparable presented as a current print is the most
        # damaging thing this brief can publish.
        raw = str(f.get("date_iso") or "").strip()[:10]
        try:
            age = (today - datetime.strptime(raw, "%Y-%m-%d").date()).days
        except ValueError:
            stale.append((f, "no verifiable date"))
            continue
        if age > MAX_FINDING_AGE_DAYS or age < -1:
            stale.append((f, f"published {raw} ({age}d old)"))
            continue
        f["age_days"] = age

        try:
            score = int(f.get("relevance", 0))
        except (TypeError, ValueError):
            score = 0
        f["relevance"] = score
        (kept if score >= MIN_RELEVANCE else dropped).append(f)

    for f, why in stale:
        print(f"[warn] {name}: REJECTED STALE — {why}: "
              f"{f.get('headline','')[:60]}", file=sys.stderr)

    kept.sort(key=lambda f: f["relevance"], reverse=True)
    print(f"[info] {name}: {len(kept)} kept, {len(dropped)} below "
          f"relevance {MIN_RELEVANCE}, {len(stale)} stale/undated")
    for f in dropped:  # never drop things silently — this is how you tune the gate
        print(f"       dropped ({f['relevance']}): {f.get('headline','')[:70]}")
    return kept


def _dedupe_key(f: dict) -> str:
    """Collapse the same story reported by two outlets into one comparison key."""
    url = re.sub(r"^https?://(www\.)?", "", str(f.get("url", "")).lower()).rstrip("/")
    head = re.sub(r"[^a-z0-9 ]", "", str(f.get("headline", "")).lower())
    head = " ".join(w for w in head.split() if w not in {
        "the", "a", "an", "for", "to", "of", "in", "on", "at", "and", "with"})
    return url if not head else head[:60]


def check_offlist_domains(findings: list[dict]) -> list[dict]:
    """Surface (or drop) findings from domains outside the approved allowlist.

    The Anthropic passes are allowlist-enforced at the API level. Grok is not —
    it searches the open web, which is exactly why it can reach the mastheads,
    but it means the config's "nothing outside this list can ever appear"
    guarantee no longer holds for its findings. Default is to report, not
    remove: set enforce_allowlist_for_grok in config.yml to restore the hard
    guarantee at the cost of losing sources you have not pre-approved.
    """
    approved = {d.lower().lstrip(".") for d in CONFIG.get("allowed_domains", [])}
    enforce = bool(CONFIG.get("enforce_allowlist_for_grok", False))
    offlist, kept = [], []
    for f in findings:
        host = re.sub(r"^www\.", "",
                      re.sub(r"^https?://", "", str(f.get("url", "")).lower())
                      .split("/")[0])
        if host and not any(host == d or host.endswith("." + d)
                            for d in approved):
            offlist.append((host, f))
            if enforce:
                continue
        kept.append(f)
    if offlist:
        hosts = sorted({h for h, _ in offlist})
        verb = "DROPPED" if enforce else "allowed (not on the allowlist)"
        print(f"[info] {len(offlist)} finding(s) from off-allowlist domains "
              f"{verb}: {hosts}", file=sys.stderr)
    return kept


def merge_sources(*groups: list[dict]) -> list[dict]:
    """Merge findings from every source, keeping the richest copy of each story.

    The same deal legitimately surfaces from both passes (the Cbus/Carindale
    sale came back from Anthropic via Inside Retail and from Grok via the AFR).
    Prefer the higher-scored copy, and prefer a masthead URL over an aggregator
    when scores tie, since that is the link the reader wants.
    """
    best: dict[str, dict] = {}
    for f in [f for g in groups for f in g]:
        k = _dedupe_key(f)
        cur = best.get(k)
        if cur is None or (f.get("relevance", 0), f.get("origin") == "grok") > \
                (cur.get("relevance", 0), cur.get("origin") == "grok"):
            best[k] = f
    merged = sorted(best.values(), key=lambda f: f.get("relevance", 0),
                    reverse=True)
    total = sum(len(g) for g in groups)
    if total != len(merged):
        print(f"[info] merged {total} findings from all sources -> "
              f"{len(merged)} after de-duplication")
    return merged


def run_research(client, window: str) -> list[dict]:
    """Run every cluster in parallel, bounded by a hard wall-clock deadline.

    Streaming means a slow-but-alive response never trips the per-request
    timeout, so without this a single crawling cluster could run past the
    workflow's budget and cost the edition. Whatever has finished by the
    deadline is what gets published.
    """
    results: dict[str, list[dict]] = {n: [] for n in RESEARCH_CLUSTERS}
    pool = concurrent.futures.ThreadPoolExecutor(
        max_workers=len(RESEARCH_CLUSTERS) + 1)
    futures = {
        pool.submit(research_cluster, client, name, focus, window): name
        for name, focus in RESEARCH_CLUSTERS.items()
    }

    # Grok runs alongside, covering the mastheads Anthropic's crawler is
    # blocked from (afr.com, theaustralian.com.au, smh.com.au and the rest).
    # Optional: no key, no Grok, and the edition still ships.
    xai_key = os.environ.get("XAI_API_KEY")
    if xai_key:
        results["grok"] = []
        futures[pool.submit(
            lambda: gate_findings("grok", grok_research.research(
                xai_key, window, AUDIENCE, RELEVANCE_RUBRIC, GEOGRAPHY,
                CONFIG.get("watchlist", {}), DEAL_THRESHOLD))
        )] = "grok"
    else:
        print("[info] XAI_API_KEY not set — skipping Grok research pass "
              "(the mastheads will be missing)", file=sys.stderr)
    try:
        for fut in concurrent.futures.as_completed(
                futures, timeout=RESEARCH_DEADLINE_S):
            name = futures[fut]
            try:
                results[name] = fut.result()
            except Exception as e:
                # One cluster failing must not cost us the edition — the
                # others still have findings the editor can work with.
                print(f"[warn] cluster {name} failed: {e}", file=sys.stderr)
    except concurrent.futures.TimeoutError:
        stalled = [futures[f] for f in futures if not f.done()]
        print(f"[warn] research deadline hit after {RESEARCH_DEADLINE_S}s — "
              f"publishing without: {stalled}", file=sys.stderr)
        for f in futures:
            f.cancel()
    finally:
        # Don't block the edition waiting on threads we've already given up on.
        pool.shutdown(wait=False)
    return check_offlist_domains(merge_sources(*results.values()))


# ----------------------------------------------------------------------------
# Pass 2 — editor
# ----------------------------------------------------------------------------
def run_editor(client, findings, asx_items, mem, label, window,
               is_friday: bool, trend_summary: str = "") -> tuple[str, str, list[dict]]:
    recent = brief_memory.recent_headlines(mem)
    tracker = brief_memory.open_deals(mem)
    week = brief_memory.week_deals(mem) if is_friday else []

    friday_block = ""
    if is_friday:
        friday_block = f"""
11. WEEK IN REVIEW (Friday only — include it today) — a short "theme of the
   week" (2-3 sentences), then an HTML <table> of the week's transactions
   with columns Asset | Sector | State | Price | Yield | Status, built ONLY
   from this week's DEAL LOG below plus today's findings. Style the table
   inline: full width, collapsed borders, th left-aligned with a bottom
   border, td padding 6px.
   THIS WEEK'S DEAL LOG: {json.dumps(week)}"""

    prompt = f"""You are the editor of "{BRIEF_NAME}" ({label}), a sharp daily email for
the Head of Asset Management at a private Australian mid-market property group
covering retail, commercial office, industrial, childcare and aged care assets.

WHO YOU ARE WRITING FOR:
{AUDIENCE}

Every line must earn its place with one of those five jobs. If an item does
not change what this team does, cut it — a short brief is a good brief.

Write today's edition from the RESEARCH FINDINGS below — verified items from
approved sources covering {window}. You have no search tool: use ONLY these
findings and the provided data. Never invent stories, figures or URLs.

FACTUAL DISCIPLINE — every claim must trace to a finding or the ASX data:
- Each finding carries "date_iso" and "age_days". Never describe an item as
  more recent than its date supports, and never imply a deal is new if it is
  not from within the last few days.
- Do NOT invent counts, streaks, trends or timeframes. Phrases like "the fifth
  centre this year", "the third such deal in 12 months" or "activity is
  accelerating" are FORBIDDEN unless that exact claim appears in a finding.
  If you only have one transaction, report one transaction.
- Do not aggregate separate findings into a pattern you have inferred, and do
  not add context from your own knowledge — your training data is older than
  this edition and will be wrong.

RESEARCH FINDINGS — each already scored 0-10 for relevance to the reader and
pre-filtered to {MIN_RELEVANCE}+, highest first. Lead with the high scorers;
a 5 or 6 only earns a slot if the section would otherwise be empty. Each
carries a "so_what" — use it as raw material for your own line, don't quote
it verbatim. Findings come from two research passes and some carry
"origin": "grok"; treat both identically on the facts. Where the same story
has both a masthead and a trade-press URL, link the one with the better
reporting — AFR and Australian paywalls are fine, the reader subscribes:
{json.dumps(findings, indent=1)}

ASX PRICE-SENSITIVE ANNOUNCEMENTS (already rendered as their own section in
the email — do NOT create a section for them, but weave any that matter into
your narrative, e.g. if a REIT announced a divestment, that can be The Big
One, linking the announcement URL).
Each carries a "company" name alongside its "code": ALWAYS write the company
name on first mention, with the ticker in brackets — "Centuria Industrial
REIT (CIP)", never a bare "CIP". The reader should not have to decode ticker
symbols. Use the bare code only on later mentions in the same item:
{json.dumps(asx_items, indent=1)}

WATCHLIST (items touching these get a leading <strong>⚑ WATCHLIST</strong>
flag and priority placement — a tenant on this list hitting administration
is bigger news than a $100m deal elsewhere). Note the "own_group" key: that
is the reader's OWN organisation, not a rival. Flag mentions of it, but never
write about it in competitor framing or explain their own deals back to them:
{json.dumps(CONFIG.get("watchlist", {}))}

OUR OWN TRACKED DATA — computed in code from every transaction this brief has
recorded, NOT from the findings. These figures are arithmetic on our own
database and are the one thing competitors cannot replicate, so reference them
in THE STRATEGIC READ where they support a point. Quote them exactly as given;
never recompute, extrapolate or round them differently:
{trend_summary}

ALREADY COVERED in the last 14 days — do not repeat unless there is a NEW
development, in which case frame it explicitly as an update ("Update: ..."):
{json.dumps(recent)}

DEAL TRACKER — deals previously reported as on-market / under LOI / in due
diligence. If today's findings resolve or move any of them, report it as a
tracked update ("Tracked: ..."). If nothing moved, stay silent on them:
{json.dumps(tracker)}

SECTIONS, in order. OMIT any section with no genuine news — do not pad it with
a placeholder line. Only if the entire edition is thin, say so once at the top
in a wry sentence:
0. THE STRATEGIC READ — 3-4 sentences, in <p> tags, written for the CEO/COO.
   Not a summary of what follows. Answer: given today's flow, what should this
   group be doing with capital — buying, selling, holding, refinancing, or
   watching? Name the evidence you are reasoning from. If the day's findings
   genuinely don't support a strategic view, say so in one line rather than
   manufacturing one — a fabricated strategic call is worse than none.
1. THE BIG ONE — most significant story, 2-3 sentences in <p> tags plus one
   sharp line on what it means for asset managers.
2. CAPITAL & FUNDING — debt costs, credit spreads, lending appetite,
   refinancing conditions, capital raisings, fund launches, institutional and
   offshore flows, cap rate direction. This is the CEO's section: give the
   number and what it does to the cost of capital or the carrying value of a
   book like theirs. Omit if there is genuinely nothing.
3. TRANSACTIONS & DISPOSALS — {DEAL_THRESHOLD}+ (alternatives excepted).
   Price, yield, vendor, purchaser, agent when reported.
   Where a peer or competitor is involved, say what their STRATEGY appears to
   be — rotating out of a sector, building scale, recycling capital — not just
   that a deal happened.
4. LEASING DESK — rents, incentives, pre-commitments, expiries. Give the
   benchmark a leasing manager could be held to.
5. TENANT WATCH — frame the "so what" for a landlord. A retailer entering
   administration belongs here even if none of their centres is named.
6. OPERATIONS & COMPLIANCE — facilities, essential services, ESG/NABERS,
   insurance, outgoings, land tax and capex. Lead with anything carrying a
   deadline or a cost the reader has to plan for.
7. CENTRE MARKETING — foot traffic, spend data, tenant-mix and repositioning.
   Omit unless there is something concrete; one item max.
8. ALTERNATIVES CORNER — childcare and aged care.
9. PEOPLE MOVES
10. PROPTECH BITE — one item max.{friday_block}

TONE: entertaining but credible — a well-read colleague with a dry sense of
humour, not a press release. Punchy. One-liners welcome. Never mocking about
job losses, administrations affecting workers, or aged care residents. At
most one or two emoji total. Numbers always precise.

FORMAT — output exactly this structure:
Line 1:  SUBJECT: <punchy subject referencing the day's best story>
Then the email body between <BRIEF> and </BRIEF>:
- HTML fragment only — no <html>/<head>/<body>, no markdown.
- <h2>SECTION NAME</h2> then <ul><li> items (The Big One uses <p>).
- Bold the key asset/party with <strong>.
- SOURCE LINKS MANDATORY on every item in every section, as
  <a href="URL">Publication Name</a>, using ONLY urls present in the
  findings or ASX data above. An item without a URL gets dropped.
- 600-900 words, scannable.
Then a deal log between <DATA> and </DATA>: a JSON array with one record per
item you included (all sections), each:
{{
  "headline": "...", "url": "...", "section": "strategic|big_one|capital|
  transactions|leasing|tenants|operations|marketing|alternatives|people|
  proptech",
  "asset": "asset/company name or null",
  "sector": "retail|office|industrial|childcare|aged_care|proptech|other",
  "state": "QLD|NSW|...|national",
  "value_aud_m": number or null, "yield_pct": number or null,
  "status": "sold|on_market|loi|due_diligence|leased|opened|closed|
  administration|appointment|other",
  "parties": ["..."],
  "vendor": "seller name or null", "purchaser": "buyer name or null",
  "buyer_type": "institutional|private|offshore|reit|syndicate|owner_occupier|
  government|null",
  "agent": "selling/leasing agency or null",
  "sqm": number or null, "wale_years": number or null,
  "date_iso": "the SOURCE article's publication date, YYYY-MM-DD, from the
  finding — NOT today's date"
}}
These records accumulate into a private comparables database that later
editions compute yield trends from, so fill every field you actually have
evidence for and leave the rest null. A guessed yield or buyer type poisons
the trend maths for months — null is always better than approximately right.
No text outside these three parts."""

    # Opus 5 thinks by default and max_tokens caps thinking + output together,
    # so this needs real headroom: the edition body, the JSON deal log, and
    # the reasoning that picks between them all come out of this budget.
    # Streamed for the same reason as the research pass — this is the longest
    # single call in the pipeline and a stall here costs the whole edition.
    with client.messages.stream(
        model=EDITOR_MODEL,
        max_tokens=16000,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        response = stream.get_final_message()
    track(EDITOR_MODEL, response)
    text = "\n".join(b.text for b in response.content if b.type == "text")

    m = re.search(r"SUBJECT:\s*(.+)", text)
    subject = m.group(1).strip() if m else f"{BRIEF_NAME} — {label}"

    m = re.search(r"<BRIEF>(.*?)</BRIEF>", text, re.DOTALL)
    if not m:
        raise RuntimeError(f"Editor output missing <BRIEF> markers:\n{text[:2000]}")
    body = m.group(1).strip()

    records: list[dict] = []
    m = re.search(r"<DATA>(.*?)</DATA>", text, re.DOTALL)
    if m:
        try:
            parsed = json.loads(m.group(1).strip())
            if isinstance(parsed, list):
                records = parsed
        except json.JSONDecodeError:
            print("[warn] deal log JSON unparseable — skipping memory append",
                  file=sys.stderr)
    return subject, body, records


# ----------------------------------------------------------------------------
# Deterministic sections & rendering
# ----------------------------------------------------------------------------
def render_asx_section(items: list[dict]) -> str:
    if not items:
        return ""
    lis = []
    for i in items:
        # Headlines come from the ASX API and insights from the model — both
        # are third-party text going into an HTML email, so escape them.
        insight_html = ""
        if i.get("insights"):
            bullets = "".join(f"<li>{html_escape(str(s))}</li>" for s in i["insights"])
            insight_html = (
                '<div style="background:#faf6ee;border-left:3px solid #e8b04b;'
                'margin:8px 0 4px 0;padding:8px 12px;font-size:14px;">'
                '<strong>🔍 What most will miss:</strong>'
                f'<ul style="margin:6px 0 0 0;">{bullets}</ul></div>'
            )
        # "Coles Group (COL)" reads far better than a bare ticker for anyone
        # who doesn't have all 37 codes memorised.
        company = i.get("company") or ""
        label = (f'{html_escape(company)} '
                 f'<span style="color:#666;">({html_escape(i["code"])})</span>'
                 if company else f'{html_escape(i["code"])}')
        lis.append(
            f'<li><strong>{label}</strong> — '
            f'{html_escape(i["header"])} '
            f'<span style="color:#888;font-size:13px;">'
            f'({html_escape(i["released"])})</span> '
            f'<a href="{html_escape(i["url"], quote=True)}">PDF</a> · '
            f'<a href="{html_escape(i["page_url"], quote=True)}">ASX page</a>'
            f'{insight_html}</li>'
        )
    lis = "".join(lis)
    return f"<h2>ASX PRICE-SENSITIVE</h2><ul>{lis}</ul>"


def known_urls(findings: list[dict], asx_items: list[dict]) -> set[str]:
    """Every URL the editor is permitted to link to."""
    urls: set[str] = set()
    for f in findings:
        if isinstance(f, dict) and f.get("url"):
            urls.add(str(f["url"]).strip())
    for i in asx_items:
        urls.update(u for u in (i.get("url"), i.get("page_url")) if u)
    return urls


def strip_unverified_links(body: str, allowed: set[str]) -> str:
    """Unwrap any <a> whose href didn't come from the research or ASX data.

    The brief's whole promise is that every figure is click-through verifiable,
    so a link the editor invented is worse than no link at all: it looks
    checkable and isn't. We keep the anchor text, drop the href, and shout
    about it in the logs.
    """
    dropped = []

    def repl(m: re.Match) -> str:
        href = html_unescape(m.group(1)).strip()
        if href in allowed:
            return m.group(0)
        dropped.append(href)
        return m.group(2)

    cleaned = re.sub(r'<a\s+href="([^"]*)"[^>]*>(.*?)</a>', repl, body,
                     flags=re.DOTALL | re.IGNORECASE)
    if dropped:
        print(f"[warn] dropped {len(dropped)} unverified link(s) from the "
              f"edition: {dropped}", file=sys.stderr)
    return cleaned


def insert_after_first_section(body: str, insert_html: str) -> str:
    """Slot the ASX section in after THE BIG ONE (i.e. before the 2nd <h2>)."""
    if not insert_html:
        return body
    first = body.find("<h2")
    second = body.find("<h2", first + 1) if first != -1 else -1
    if second == -1:
        return insert_html + body
    return body[:second] + insert_html + body[second:]


def render_signals_strip(signals: list[tuple[str, str]]) -> str:
    if not signals:
        return ""
    pills = "".join(
        f'<td style="padding:6px 14px 6px 0;white-space:nowrap;">'
        f'<span style="color:#c9c9d9;font-size:11px;">{label}</span><br>'
        f'<span style="color:#ffffff;font-size:14px;font-weight:bold;">{val}'
        f"</span></td>"
        for label, val in signals
    )
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" '
        'style="margin-top:12px;font-family:Arial,sans-serif;"><tr>'
        f"{pills}</tr></table>"
    )


def get_shitpost() -> str:
    api_key = os.environ.get("XAI_API_KEY")
    if not api_key:
        return ""
    try:
        # xAI's Live Search API was retired (it 410s). The replacement is the
        # Agent Tools API on /v1/responses with an x_search tool. This must
        # stay a real search: without one the model will happily invent a
        # quote and attribute it to a real @handle.
        r = grok_research.post_with_retry(
            api_key,
            {
                "model": "grok-4.5",
                "tools": [{"type": "x_search"}],
                "input": (
                    "Search X for funny, witty or absurd posts from the "
                    "last 3 days about commercial real estate, property "
                    "investing, landlords, leasing, retail tenants or "
                    "proptech. Australian preferred but not required. "
                    "Pick the single funniest REAL post you actually found — "
                    "never invent one or paraphrase from memory. Reply ONLY "
                    "with an HTML fragment: <p>the post text in quotes — "
                    "<strong>@handle</strong></p> then one dry line of "
                    "commentary in a second <p>. Nothing offensive or "
                    "punching down. If the search returns nothing suitable, "
                    "reply with exactly: NONE"
                ),
            },
            timeout=180,
        )
        r.raise_for_status()
        content = "".join(
            c.get("text", "")
            for o in r.json().get("output", []) if o.get("type") == "message"
            for c in o.get("content", [])
        ).strip()
        if not content or content.strip().upper().startswith("NONE"):
            return ""
        content = re.sub(r"^```(?:html)?|```$", "", content).strip()
        if "<p>" not in content:
            content = f"<p>{content}</p>"
        return f"<h2>SHITPOST OF THE DAY</h2>{content}"
    except Exception as e:
        print(f"[warn] Grok section skipped: {e}", file=sys.stderr)
        return ""


def render_email(body: str, shitpost: str, label: str,
                 signals_html: str) -> str:
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background-color:#f4f2ee;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
<tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="640" cellpadding="0" cellspacing="0"
       style="max-width:640px;width:100%;background:#ffffff;border-radius:8px;overflow:hidden;">
  <tr><td style="background:#1a1a2e;padding:28px 32px;">
    <div style="font-family:Georgia,serif;font-size:26px;font-weight:bold;color:#ffffff;">
      {BRIEF_NAME}</div>
    <div style="font-family:Arial,sans-serif;font-size:13px;color:#c9c9d9;margin-top:6px;">
      {label} · Retail · Office · Industrial · Childcare · Aged Care</div>
    {signals_html}
  </td></tr>
  <tr><td style="padding:28px 32px;font-family:Arial,sans-serif;font-size:15px;
                 line-height:1.55;color:#2b2b2b;">
    <style>
      h2 {{ font-family: Georgia, serif; font-size: 17px; color: #1a1a2e;
           border-bottom: 2px solid #e8b04b; padding-bottom: 4px;
           margin: 26px 0 10px 0; letter-spacing: 0.5px; }}
      ul {{ margin: 8px 0 0 0; padding-left: 20px; }}
      li {{ margin-bottom: 10px; }}
      a  {{ color: #b05c1e; }}
      p  {{ margin: 8px 0; }}
      table.deals {{ width: 100%; border-collapse: collapse; }}
    </style>
    {body}
    {shitpost}
  </td></tr>
  <tr><td style="background:#f4f2ee;padding:18px 32px;font-family:Arial,sans-serif;
                 font-size:12px;color:#888;">
    Compiled each weekday morning from an approved-source allowlist plus the
    ASX price-sensitive feed. Every item is linked — click through and verify
    figures before relying on them.
  </td></tr>
</table>
</td></tr></table>
</body></html>"""


# ----------------------------------------------------------------------------
# Persistence & delivery
# ----------------------------------------------------------------------------
def archive_edition(html: str, date_iso: str) -> None:
    docs = os.path.join(ROOT, "docs")
    os.makedirs(docs, exist_ok=True)
    with open(os.path.join(docs, f"{date_iso}.html"), "w") as f:
        f.write(html)
    editions = sorted(
        (f for f in os.listdir(docs) if re.match(r"\d{4}-\d{2}-\d{2}\.html$", f)),
        reverse=True,
    )
    links = "".join(
        f'<li><a href="{e}">{e[:-5]}</a></li>' for e in editions
    )
    with open(os.path.join(docs, "index.html"), "w") as f:
        f.write(
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            f"<title>{BRIEF_NAME} — archive</title></head>"
            "<body style='font-family:Georgia,serif;max-width:640px;"
            "margin:40px auto;'>"
            f"<h1>{BRIEF_NAME}</h1><h3>Archive</h3><ul>{links}</ul>"
            "</body></html>"
        )


def send_email(subject: str, html: str) -> None:
    sender = os.environ["GMAIL_ADDRESS"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    raw = os.environ.get("RECIPIENT_EMAIL") or sender
    recipients = [r.strip() for r in raw.split(",") if r.strip()]
    if not recipients:
        raise RuntimeError("No recipients configured")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{BRIEF_NAME} <{sender}>"
    msg["To"] = sender  # recipients are BCC'd; To shows the sender only
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, recipients, msg.as_string())
    print(f"Sent '{subject}' to {len(recipients)} recipient(s)")


def main() -> None:
    now, label, window, lookback_hours = date_window()
    is_friday = now.weekday() == 4
    print(f"Generating {BRIEF_NAME} for {label} ...")

    mem = brief_memory.load()
    since = now - timedelta(hours=lookback_hours)

    print("Fetching ASX price-sensitive announcements ...")
    asx_items = asx_feed.price_sensitive(CONFIG.get("asx_tickers", []), since)
    print(f"  {len(asx_items)} announcements in window")

    # Bounded so the whole run stays inside the workflow's timeout: a stalled
    # request fails fast and loudly instead of silently eating the budget.
    client = anthropic.Anthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        timeout=300.0,
        max_retries=1,
    )

    if asx_items:
        print("Deep-reading substantive announcements ...")
        asx_insights.enrich(client, RESEARCH_MODEL, asx_items)

    print(f"Research pass ({len(RESEARCH_CLUSTERS)} clusters, "
          f"allowlist-enforced) ...")
    findings = run_research(client, window)

    trends = portfolio_trends.compute(mem, now)
    print(f"Trend database: {trends['total_tracked']} transactions tracked, "
          f"{trends['recent_count']} in the last {trends['window_days']} days")

    print("Editor pass ...")
    subject, body, records = run_editor(
        client, findings, asx_items, mem, label, window, is_friday,
        portfolio_trends.summary_for_editor(trends)
    )

    body = strip_unverified_links(body, known_urls(findings, asx_items))
    body = insert_after_first_section(body, render_asx_section(asx_items))

    # Deterministic blocks, appended after the written sections: these are
    # arithmetic on our own data and known-future dates, so they never pass
    # through the model and cannot be hallucinated.
    body += portfolio_trends.render(trends)
    body += forward_calendar.render(
        forward_calendar.rba_dates(CONFIG, now.date()),
        forward_calendar.pending_results(CONFIG.get("asx_tickers", [])),
        brief_memory.open_deals(mem),
    )
    signals_html = render_signals_strip(market_signals.collect())
    shitpost = get_shitpost()
    html = render_email(body, shitpost, label, signals_html)

    if os.environ.get("DRY_RUN"):
        with open("brief_preview.html", "w") as f:
            f.write(html)
        print(f"DRY_RUN — wrote brief_preview.html. Subject: {subject}")
        report_cost()
        return

    date_iso = now.strftime("%Y-%m-%d")
    if os.path.exists(os.path.join(ROOT, "docs", f"{date_iso}.html")) \
            and not os.environ.get("FORCE_SEND"):
        print(f"An edition for {date_iso} already exists — not sending twice. "
              f"Set FORCE_SEND=1 to override.", file=sys.stderr)
        return

    send_email(subject, html)
    archive_edition(html, date_iso)
    brief_memory.append(mem, records, date_iso)
    brief_memory.save(mem)
    print(f"Archived edition and logged {len(records)} records to memory.")
    report_cost()


def _fatal(msg: str) -> None:
    print(f"\nFAILED: {msg}", file=sys.stderr)
    report_cost()
    sys.exit(1)


if __name__ == "__main__":
    # Account-level failures are the common cause of a dead 5:30am run, and a
    # raw traceback buries the one line that says what to do about it.
    try:
        main()
    except anthropic.AuthenticationError:
        _fatal("ANTHROPIC_API_KEY rejected — check the secret is set and valid.")
    except anthropic.BadRequestError as e:
        if "credit balance" in str(e).lower():
            _fatal("Anthropic account is out of credit — top up at "
                   "https://console.anthropic.com/settings/billing")
        raise
    except anthropic.RateLimitError:
        _fatal("Rate limited by the Anthropic API — the run was abandoned. "
               "Re-run from the Actions tab.")
