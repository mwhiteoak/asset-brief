"""Second research source: xAI/Grok, covering what Anthropic's crawler cannot.

Anthropic's web_search is blocked by every major Australian masthead — afr.com,
theaustralian.com.au, smh.com.au, theage.com.au, couriermail.com.au,
brisbanetimes.com.au, abc.net.au, news.com.au, theguardian.com. That is most of
the industry's actual reporting, and no allowlist tuning gets it back.

xAI's crawler is not subject to those blocks, so this module runs a parallel
research pass over exactly that territory and returns findings in the same
schema as the Anthropic clusters. The two sets are merged, de-duplicated and
put through the identical relevance gate and recency guard downstream — this
module gets no special trust.

Fail-safe: any error returns [] and the edition ships on the Anthropic
findings alone.
"""

import json
import re
import sys
import time

import requests

ENDPOINT = "https://api.x.ai/v1/responses"
MODEL = "grok-4.5"
TIMEOUT_S = 600


def post_with_retry(api_key: str, body: dict, timeout: int = TIMEOUT_S,
                    attempts: int = 4):
    """POST to xAI, retrying the throttling responses.

    Back-to-back calls to /v1/responses return 403 or 429 — the shitpost call
    was being refused seconds after the research call finished. Both go
    through here so neither is lost to a transient throttle.
    """
    delay = 5
    last = None
    for i in range(attempts):
        r = requests.post(
            ENDPOINT,
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            json=body, timeout=timeout,
        )
        if r.status_code not in (403, 429, 500, 502, 503, 529):
            r.raise_for_status()
            return r
        last = r
        if i < attempts - 1:
            print(f"[info] xAI {r.status_code} — retrying in {delay}s",
                  file=sys.stderr)
            time.sleep(delay)
            delay *= 2
    last.raise_for_status()
    return last

# The outlets Anthropic cannot reach. This is the whole point of the module,
# so it is stated to the model explicitly rather than left to chance.
PRIORITY_SOURCES = [
    "afr.com", "theaustralian.com.au", "smh.com.au", "theage.com.au",
    "couriermail.com.au", "brisbanetimes.com.au", "businessnewsaustralia.com",
    "australianpropertyjournal.com.au", "theurbandeveloper.com",
    "commercialrealestate.com.au", "realcommercial.com.au",
    "insideretail.com.au", "shoppingcentrenews.com.au", "thesector.com.au",
    "australianageingagenda.com.au", "theweeklysource.com.au",
]


PROPERTY_COVERAGE = '''COVER ALL OF THE FOLLOWING. The first two are for the executive readers and
are the most commonly missed, so search them explicitly rather than hoping
they surface:

  1. CAPITAL AND FUNDING — cost of debt for commercial property, credit
     spreads, bank and non-bank lending appetite, refinancing conditions and
     debt maturity walls, A-REIT equity raisings, wholesale fund launches and
     redemptions, institutional and offshore capital flows into or out of
     Australian property, and cap rate / valuation direction with evidence.
  2. STRATEGIC AND COMPETITIVE — what property groups, A-REITs, super funds
     and institutions are doing strategically: portfolio rotation, sector
     entries and exits, mandate changes, platform acquisitions, management
     internalisations, joint ventures.
  3. Transactions (sales, acquisitions, disposals, campaigns, LOIs, due
     diligence) — minimum {deal_threshold}, alternatives may be smaller.
     ALWAYS capture price AND yield/cap rate where reported.
  4. Leasing — deals, pre-commitments, incentives, rents, expiries.
  5. Tenant health — expansions, closures, administrations, rent defaults.
  6. Childcare and aged care operators, including funding and subsidy changes.
  7. Building operations and compliance — ESG, NABERS, essential services,
     insurance, land tax, outgoings, construction costs.
  8. Centre marketing and foot traffic; people moves; proptech.'''


def _prompt(window: str, audience: str, rubric: str, geography: str,
            watchlist: dict, deal_threshold: str, portfolio: str = "",
            coverage: str = "", brief_desc: str = "", sources: list | None = None) -> str:
    coverage = coverage or PROPERTY_COVERAGE.format(deal_threshold=deal_threshold)
    brief_desc = brief_desc or "a daily Australian commercial property brief"
    sources = sources or PRIORITY_SOURCES
    return f"""You are a research analyst for {brief_desc}. Search the web for
genuine news published within {window}.

WHO YOU ARE WRITING FOR:
{audience}

Geography: {geography}

{coverage}

PRIORITISE THESE OUTLETS — they are the ones our other research pass cannot
reach, so they are the whole reason you are being asked:
{", ".join(sources)}

{portfolio}

WATCHLIST — anything touching these is top priority, tag it "watchlist":
{json.dumps(watchlist)}

RELEVANCE SCORING:
{rubric}

RECENCY IS A HARD REQUIREMENT. Only report news published within {window}.
An old deal presented as current is the worst failure this brief can make,
because the reader makes real decisions on it. Establish each
article's ACTUAL publication date from the page. Never guess it, never infer
it from search ranking, and NEVER substitute today's date. If you genuinely
cannot establish a date, still return the finding with "date_iso": null — a
downstream filter rejects and logs undated items, so returning it costs
nothing and silently dropping it hides the loss.

Paywalled articles are fine and wanted: report the headline, whatever detail
is visible, and the real URL. The reader subscribes and clicks through.

Output ONLY a JSON array between <FINDINGS> and </FINDINGS>. Each element:
{{
  "headline": "...",
  "summary": "2-3 sentences with the concrete facts — price, yield, parties,
              agents, sqm, terms — whatever was actually reported",
  "url": "the real article URL",
  "source": "publication name",
  "date_iso": "YYYY-MM-DD actual publication date, or null",
  "sector": "retail|office|industrial|childcare|aged_care|proptech|other",
  "state": "QLD|NSW|VIC|WA|SA|ACT|TAS|NT|national",
  "discipline": "capital_funding|strategy|property_management|leasing|
                 marketing|transactions|facilities_management",
  "level": "executive|operational|both — who this actually matters to",
  "yield_pct": number or null (cap rate if reported — this is the scarcest
               and most valuable field in the whole brief, never guess it),
  "value_aud_m": number or null,
  "relevance": 0-10 per the rubric,
  "so_what": "one concrete sentence on what this means for the reader",
  "tags": ["watchlist" if applicable, "transaction"/"leasing"/"tenant"/
           "people"/"regulatory" etc.]
}}

Rules: every finding MUST have a real URL you actually retrieved. Never
fabricate or reconstruct a URL, a figure or a quote. Do not omit findings
because you scored them low — return them and let the filter decide. No text
outside the markers."""


def resolve_dates(api_key: str, findings: list[dict]) -> dict:
    """Look up publication dates for high-value findings that arrived undated.

    The recency guard discards anything it cannot date, which is correct — but
    it threw away a childcare tenant defaulting on rent across 31 properties
    purely because the page carried no visible date. Rather than weakening the
    guard, this re-checks only the findings worth the extra call, by fetching
    the article and reading the date off it.

    Returns {url: "YYYY-MM-DD"} for whatever it could establish. A URL missing
    from the result stays undated and is still rejected.
    """
    if not findings:
        return {}
    listing = "\n".join(f'{i + 1}. {f.get("url")}' for i, f in enumerate(findings))
    prompt = f"""For each URL below, open the page and establish its ACTUAL publication
date — the date the article was published, not today's date, not a "last
updated" date on a listing page, and not a date you infer from the content.

{listing}

Look for a dateline, byline date, <time> element, or a date in the URL slug.
If a page has no publication date you can actually see, say null for it. A
wrong date is far worse than no date here: these feed a comparables database
that prices real assets.

Output ONLY a JSON object between <DATES> and </DATES>, mapping each URL to
"YYYY-MM-DD" or null:
{{"https://...": "2026-08-11", "https://...": null}}"""
    try:
        r = post_with_retry(api_key, {
            "model": MODEL,
            "tools": [{"type": "web_search"}],
            "input": prompt,
        }, timeout=300)
        text = "".join(
            c.get("text", "")
            for o in r.json().get("output", []) if o.get("type") == "message"
            for c in o.get("content", []))
        m = re.search(r"<DATES>(.*?)</DATES>", text, re.DOTALL)
        if not m:
            return {}
        data = json.loads(m.group(1).strip())
        out = {k: v for k, v in data.items()
               if isinstance(v, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", v)}
        print(f"[info] date recheck: resolved {len(out)}/{len(findings)}")
        return out
    except Exception as e:
        print(f"[warn] date recheck failed: {e}", file=sys.stderr)
        return {}


def comparables(api_key: str, window: str, geography: str,
                deal_threshold: str) -> list[dict]:
    """Hunt specifically for transactions reporting BOTH a price and a yield.

    The general research pass captures cap rates only incidentally — one usable
    comparable in twenty-one records. The trend engine needs three per sector
    before it can publish anything, so this pass exists purely to feed it.
    """
    prompt = f"""Find Australian commercial property TRANSACTIONS reported within {window}
where BOTH a price AND a yield (cap rate) are stated. That combination is the
entire point of this search — a sale without a reported yield is not useful
here, and you must never estimate, derive or infer a yield that the source did
not state.

Sectors: retail (especially neighbourhood, convenience and large format),
office, industrial, childcare, aged care, medical, service stations, fast food
and other convenience-based net lease assets.
Geography: {geography}
Minimum {deal_threshold}, except childcare/aged care/net lease which are
routinely smaller and still count.

Search agency press rooms as well as trade press — Burgess Rawson, Stonebridge,
CBRE, JLL, Colliers, Cushman & Wakefield, Knight Frank, Savills, Ray White
Commercial and similar publish auction and portfolio results with yields.

Output ONLY a JSON array between <FINDINGS> and </FINDINGS>:
{{
  "headline": "...",
  "summary": "the concrete facts: price, yield, parties, agent, WALE, sqm",
  "url": "the real article URL you retrieved",
  "source": "publication or agency name",
  "date_iso": "YYYY-MM-DD actual publication date, or null",
  "sector": "retail|office|industrial|childcare|aged_care|other",
  "state": "QLD|NSW|VIC|WA|SA|ACT|TAS|NT|national",
  "discipline": "transactions",
  "level": "both",
  "value_aud_m": number (millions AUD),
  "yield_pct": number — the REPORTED yield, never your own calculation,
  "relevance": 0-10,
  "so_what": "what this comparable implies for a similar asset",
  "tags": ["transaction", "comparable"]
}}

Every element MUST have both value_aud_m and yield_pct as numbers — omit any
finding missing either. Return [] if nothing qualifies; an empty result is
correct and expected on many days. No text outside the markers."""
    try:
        r = post_with_retry(api_key, {
            "model": MODEL, "tools": [{"type": "web_search"}], "input": prompt,
        })
        payload = r.json()
    except Exception as e:
        print(f"[warn] grok comparables failed: {e}", file=sys.stderr)
        return []

    u = payload.get("usage", {}) or {}
    print(f"[info] grok comparables: {u.get('input_tokens', 0):,} in / "
          f"{u.get('output_tokens', 0):,} out")
    text = "".join(
        c.get("text", "")
        for o in payload.get("output", []) if o.get("type") == "message"
        for c in o.get("content", []))
    m = re.search(r"<FINDINGS>(.*?)</FINDINGS>", text, re.DOTALL)
    if not m:
        return []
    try:
        rows = json.loads(m.group(1).strip())
    except json.JSONDecodeError:
        return []
    out = []
    for f in rows if isinstance(rows, list) else []:
        # The whole point of this pass — drop anything without both numbers.
        if (isinstance(f, dict) and f.get("url")
                and isinstance(f.get("value_aud_m"), (int, float))
                and isinstance(f.get("yield_pct"), (int, float))):
            f["origin"] = "grok_comps"
            f["status"] = "sold"
            out.append(f)
    print(f"[info] grok comparables: {len(out)} priced-and-yielded transactions")
    return out


PROPERTY_INTEL = '''Search for Australian commercial property MARKET INTELLIGENCE published
within {window}. This is deliberately NOT breaking transaction news — it is
the material that shapes strategy and gets discussed all week. Hunt each of
these four categories explicitly:

  1. RESEARCH AND BENCHMARK RELEASES — the authoritative periodic reports:
     Property Council Office Market Report (vacancy by CBD and grade), JLL,
     CBRE, Knight Frank, Colliers, Cushman & Wakefield, Savills and MSCI
     research; retail turnover and foot traffic indices; industrial vacancy
     and rent series; cap rate surveys; construction cost indices. Capture the
     actual NUMBERS and the direction of travel.
  2. ASSETS AND PORTFOLIOS NEWLY LAUNCHED TO MARKET — campaigns opening,
     expressions of interest called, assets listed for the first time in
     years, portfolios being shopped. What is COMING to market matters as
     much as what has sold; the reader buys and sells for a living.
  3. FUND, PLATFORM AND CORPORATE M&A — funds being wound up, gated or
     restructured; management platforms and rent rolls changing hands;
     auction processes for property businesses; REIT mergers, privatisations
     and takeover approaches; mandate wins and losses.
  4. POLICY AND PLANNING DECISIONS with a property consequence — planning
     reform, activity centre and rezoning decisions, foreign investment rule
     changes, land tax and rates rulings, tenancy or retail lease law.'''


def market_intelligence(api_key: str, window: str, geography: str,
                        watchlist: dict, categories: str = "") -> list[dict]:
    categories = categories or PROPERTY_INTEL
    """The categories the general news pass systematically misses.

    A gap analysis against an independent "top 15 stories" list found four
    blind spots, all of them things the industry discusses but which don't
    read as breaking news: benchmark research releases, assets newly launched
    to market, institutional fund and platform M&A, and policy decisions. The
    general pass hunts events; this hunts the slower-moving material that
    actually shapes strategy.
    """
    prompt = f"""{categories}

Geography: {geography}
Give priority to anything touching this watchlist: {json.dumps(watchlist)}

RECENCY: only material published within {window}. Establish each item's real
publication date from the page; if you cannot, return it with "date_iso": null
and a downstream filter will handle it. Never guess a date or substitute
today's.

Output ONLY a JSON array between <FINDINGS> and </FINDINGS>, each element:
{{
  "headline": "...",
  "summary": "2-3 sentences carrying the actual figures — vacancy rates,
              rents, cap rates, dollar values, dates. A research release
              without its numbers is useless here.",
  "url": "the real article or report URL you retrieved",
  "source": "publication or research house",
  "date_iso": "YYYY-MM-DD or null",
  "category": "research|to_market|fund_ma|policy",
  "sector": "retail|office|industrial|childcare|aged_care|other",
  "state": "QLD|NSW|VIC|WA|SA|ACT|TAS|NT|national",
  "discipline": "capital_funding|strategy|transactions|leasing|
                 facilities_management",
  "level": "executive|operational|both",
  "relevance": 0-10,
  "so_what": "one concrete sentence on the implication",
  "tags": ["research"/"to_market"/"fund_ma"/"policy", "watchlist" if relevant]
}}
Never fabricate a URL, a figure or a report. Return [] if nothing qualifies.
No text outside the markers."""
    try:
        r = post_with_retry(api_key, {
            "model": MODEL, "tools": [{"type": "web_search"}], "input": prompt,
        })
        payload = r.json()
    except Exception as e:
        print(f"[warn] grok market-intel failed: {e}", file=sys.stderr)
        return []

    u = payload.get("usage", {}) or {}
    print(f"[info] grok market-intel: {u.get('input_tokens', 0):,} in / "
          f"{u.get('output_tokens', 0):,} out")
    text = "".join(
        c.get("text", "")
        for o in payload.get("output", []) if o.get("type") == "message"
        for c in o.get("content", []))
    m = re.search(r"<FINDINGS>(.*?)</FINDINGS>", text, re.DOTALL)
    if not m:
        return []
    try:
        rows = json.loads(m.group(1).strip())
    except json.JSONDecodeError:
        return []
    out = []
    for f in rows if isinstance(rows, list) else []:
        if isinstance(f, dict) and f.get("url"):
            f["origin"] = "grok_intel"
            out.append(f)
    by_cat = {}
    for f in out:
        by_cat[f.get("category", "?")] = by_cat.get(f.get("category", "?"), 0) + 1
    print(f"[info] grok market-intel: {len(out)} findings {by_cat}")
    return out


def research(api_key: str, window: str, audience: str, rubric: str,
             geography: str, watchlist: dict, deal_threshold: str,
             portfolio: str = "", coverage: str = "", brief_desc: str = "",
             sources: list | None = None) -> list[dict]:
    """Return findings from Grok, or [] on any failure."""
    try:
        r = post_with_retry(api_key, {
            "model": MODEL,
            "tools": [{"type": "web_search"}],
            "input": _prompt(window, audience, rubric, geography,
                             watchlist, deal_threshold, portfolio, coverage,
                             brief_desc, sources),
        })
        payload = r.json()
    except Exception as e:
        print(f"[warn] grok research failed: {e}", file=sys.stderr)
        return []

    usage = payload.get("usage", {}) or {}
    print(f"[info] grok research: {usage.get('input_tokens', 0):,} in / "
          f"{usage.get('output_tokens', 0):,} out")

    text = "".join(
        c.get("text", "")
        for o in payload.get("output", []) if o.get("type") == "message"
        for c in o.get("content", [])
    )
    m = re.search(r"<FINDINGS>(.*?)</FINDINGS>", text, re.DOTALL)
    if not m:
        print("[warn] grok research: no FINDINGS markers", file=sys.stderr)
        return []
    try:
        findings = json.loads(m.group(1).strip())
    except json.JSONDecodeError as e:
        print(f"[warn] grok research: bad JSON ({e})", file=sys.stderr)
        return []
    if not isinstance(findings, list):
        return []

    out = []
    for f in findings:
        if isinstance(f, dict) and f.get("url"):
            # Marked so the editor and the logs can tell the sources apart.
            f["origin"] = "grok"
            out.append(f)
    print(f"[info] grok research: {len(out)} raw findings")
    return out
