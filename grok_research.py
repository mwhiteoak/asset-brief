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


def _prompt(window: str, audience: str, rubric: str, geography: str,
            watchlist: dict, deal_threshold: str) -> str:
    return f"""You are a research analyst for a daily Australian commercial property
brief. Search the web for genuine news published within {window}.

WHO YOU ARE WRITING FOR:
{audience}

Geography: {geography}

COVER ALL OF THE FOLLOWING. The first two are for the executive readers and
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
  8. Centre marketing and foot traffic; people moves; proptech.

PRIORITISE THESE OUTLETS — they are the ones our other research pass cannot
reach, so they are the whole reason you are being asked:
{", ".join(PRIORITY_SOURCES)}

WATCHLIST — anything touching these is top priority, tag it "watchlist":
{json.dumps(watchlist)}

RELEVANCE SCORING:
{rubric}

RECENCY IS A HARD REQUIREMENT. Only report news published within {window}.
An old deal presented as current is the worst failure this brief can make,
because the reader prices real assets off these comparables. Establish each
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


def research(api_key: str, window: str, audience: str, rubric: str,
             geography: str, watchlist: dict, deal_threshold: str) -> list[dict]:
    """Return findings from Grok, or [] on any failure."""
    try:
        r = post_with_retry(api_key, {
            "model": MODEL,
            "tools": [{"type": "web_search"}],
            "input": _prompt(window, audience, rubric, geography,
                             watchlist, deal_threshold),
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
