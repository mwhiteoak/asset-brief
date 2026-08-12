"""Deep-read analysis of substantive ASX announcements.

For announcements worth reading (results packs, annual reports, investor
presentations, strategy/portfolio updates), this module downloads the actual
PDF from the ASX CDN, extracts the text, and runs a dedicated analyst call
whose brief is explicitly NOT the headline numbers — it hunts for the
property-relevant detail buried in the notes that most readers skim past:
cap rate movements by sector/state, WALE and expiry cliffs, incentive and
occupancy trends, impairments and onerous lease provisions, store network
plans, divestment hints, capex signals.

Insights render as a nested block under the announcement in the ASX section.
Everything is fail-safe: any download/extraction/analysis error just means
that announcement appears as a plain link, as before.
"""

import io
import json
import re
import sys

import requests

MAX_ANALYSES_PER_EDITION = 3
MAX_PDF_MB = 40
MAX_TEXT_CHARS = 250_000  # ~60k tokens; enough for the meat of a results pack

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

# Headline keywords that mark an announcement as worth a deep read, weighted.
KEYWORD_SCORES = [
    (10, ["annual report", "full year result", "fy result", "half year result",
          "hy result", "full-year", "half-year", "annual results"]),
    (8,  ["results presentation", "investor presentation", "results announcement",
          "appendix 4e", "appendix 4d"]),
    (6,  ["trading update", "strategy", "portfolio update", "market update",
          "guidance"]),
    (5,  ["divestment", "acquisition", "sale of", "disposal"]),
    (3,  ["agm", "operational update"]),
]
SKIP_PATTERNS = ["dividend/distribution", "change of director", "appendix 3",
                 "notification of", "cleansing", "becoming a substantial",
                 "ceasing to be", "proxy", "update - dividend"]


def _score(header: str) -> int:
    h = header.lower()
    if any(p in h for p in SKIP_PATTERNS):
        return 0
    return max((s for s, kws in KEYWORD_SCORES if any(k in h for k in kws)),
               default=0)


def select_candidates(asx_items: list[dict]) -> list[dict]:
    scored = [(s, i) for i in asx_items if (s := _score(i["header"])) > 0]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [i for _, i in scored[:MAX_ANALYSES_PER_EDITION]]


def _fetch_pdf(url: str) -> tuple[str, bytes, int]:
    """Download a PDF; return (extracted_text, raw_bytes, page_count)."""
    from pypdf import PdfReader
    r = requests.get(url, headers=UA, timeout=60)
    r.raise_for_status()
    if len(r.content) > MAX_PDF_MB * 1024 * 1024:
        raise ValueError(f"PDF too large ({len(r.content)//1048576}MB)")
    reader = PdfReader(io.BytesIO(r.content))
    pages = []
    for n, page in enumerate(reader.pages, 1):
        try:
            txt = page.extract_text() or ""
        except Exception:
            txt = ""
        if txt.strip():
            pages.append(f"[page {n}]\n{txt}")
    text = "\n\n".join(pages)
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS] + "\n\n[TRUNCATED]"
    return text, r.content, len(reader.pages)


ANALYST_PROMPT = """You are a buy-side property analyst reading an ASX announcement for the
Head of Asset Management at a private Australian property group that owns
retail, commercial office, industrial, childcare and aged care assets.

Company: {code} — announcement: "{header}"

Your job is NOT the headline numbers — assume the reader will see revenue,
profit and DPS everywhere. Hunt for what most readers will MISS: detail
buried in the notes, appendices and fine print that matters to a landlord,
asset manager or acquirer. Examples of what qualifies:
- cap rate / discount rate movements by sector, state or individual asset
- WALE shifts, lease expiry concentrations, incentive levels, occupancy
  trends, arrears or rent relief mentions
- impairments, onerous lease provisions, make-good liabilities
- store/centre network plans: openings, closures, downsizes, relocations,
  formats being trialled (a tenant's network plan is a landlord's pipeline)
- divestment or acquisition hints, assets "held for sale", strategic reviews
- capex plans, development pipeline changes, land banking
- covenant headroom, hedging, debt expiry walls that could force sales
- anything QLD/NSW-specific

Rules: only genuine findings actually present in the document — quality over
quantity, 2 sharp insights beat 5 padded ones. Each insight is ONE sentence
with the specific figure and the page reference from the [page N] markers.
If the document truly contains nothing non-obvious, return fewer items or
an empty array. Never invent figures.

Output ONLY a JSON array of strings between <INSIGHTS> and </INSIGHTS>.

DOCUMENT TEXT:
{text}"""


def analyze(client, model: str, item: dict) -> list[str]:
    """Returns a list of insight sentences for one announcement (or [])."""
    try:
        text, raw, n_pages = _fetch_pdf(item["url"])
        if len(text) >= 2000:
            # Text path — cheap and works for most reports/letters
            content = ANALYST_PROMPT.format(
                code=item["code"], header=item["header"], text=text
            )
        # 20MB raw -> ~27MB base64, which still clears the 32MB request ceiling.
        # Anything larger is rejected by the API after we've already paid for
        # the download and the encode.
        elif n_pages <= 100 and len(raw) <= 20 * 1024 * 1024:
            # Image-heavy deck (charts, scanned pages) — send the PDF
            # natively so Claude reads it visually. Page refs still work.
            import base64
            print(f"[info] insights {item['code']}: image-heavy PDF "
                  f"({n_pages}p) — using native PDF reading", file=sys.stderr)
            content = [
                {"type": "document",
                 "source": {"type": "base64",
                            "media_type": "application/pdf",
                            "data": base64.b64encode(raw).decode()}},
                {"type": "text",
                 "text": ANALYST_PROMPT.format(
                     code=item["code"], header=item["header"],
                     text="[document attached above — cite page numbers "
                          "from the PDF itself]")},
            ]
        else:
            print(f"[warn] insights {item['code']}: image-only PDF too large "
                  f"({n_pages}p) — skipping analysis", file=sys.stderr)
            return []
        response = client.messages.create(
            model=model,
            max_tokens=1500,
            messages=[{"role": "user", "content": content}],
        )
        out = "\n".join(b.text for b in response.content if b.type == "text")
        m = re.search(r"<INSIGHTS>(.*?)</INSIGHTS>", out, re.DOTALL)
        if not m:
            return []
        insights = json.loads(m.group(1).strip())
        return [str(i) for i in insights if str(i).strip()][:5] \
            if isinstance(insights, list) else []
    except Exception as e:
        print(f"[warn] insights {item['code']}: {e}", file=sys.stderr)
        return []


def enrich(client, model: str, asx_items: list[dict]) -> None:
    """Attach item['insights'] to the top candidate announcements, in place."""
    for item in select_candidates(asx_items):
        print(f"  deep-reading {item['code']}: {item['header'][:60]}")
        insights = analyze(client, model, item)
        if insights:
            item["insights"] = insights
            print(f"    -> {len(insights)} insights")
