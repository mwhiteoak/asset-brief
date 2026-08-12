"""Forward calendar — what is coming, not what already happened.

Most of what separates an executive read from an operational one is tense. This
module assembles the known-future items the pipeline can establish without
guessing: scheduled RBA decisions, ASX results the companies have themselves
flagged via Advance Notice announcements, and open deals from the tracker that
should resolve.

Everything here is derived from recorded data or config. Nothing is inferred,
because a calendar that is wrong is worse than no calendar.
"""

import sys
from datetime import datetime

import requests

import asx_feed

ASX_API = ("https://asx.api.markitdigital.com/asx-research/1.0/"
           "companies/{code}/announcements")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
      "Accept": "application/json"}

# Companies flag their own reporting dates through these headline types.
NOTICE_MARKERS = ("advance notice", "notice of results", "results date",
                  "date of results", "half year results date")


def rba_dates(config: dict, today) -> list[str]:
    """Upcoming RBA decisions from config (they publish the year's schedule)."""
    out = []
    for d in config.get("rba_meeting_dates", []) or []:
        try:
            dt = datetime.strptime(str(d), "%Y-%m-%d").date()
        except ValueError:
            continue
        if dt >= today:
            out.append(dt)
    return [d.strftime("%a %d %b") for d in sorted(out)[:3]]


def pending_results(tickers: list[str],
                    lookback_items: int = 20) -> list[tuple[str, str]]:
    """Tickers that have lodged an Advance Notice — i.e. results are imminent.

    We report only that a company has flagged results, never a specific date:
    the date lives inside the PDF and guessing it would put a wrong figure in
    front of the reader.
    """
    flagged = {}
    for code in tickers:
        code = str(code).strip().upper()
        try:
            r = requests.get(ASX_API.format(code=code),
                             params={"itemsPerPage": lookback_items},
                             headers=UA, timeout=20)
            if r.status_code != 200:
                continue
            data = r.json().get("data", {})
            for a in data.get("items", []):
                head = (a.get("headline") or "").lower()
                if any(m in head for m in NOTICE_MARKERS):
                    flagged[code] = asx_feed.tidy_name(
                        data.get("displayName", ""))
                    break
        except Exception as e:
            print(f"[warn] calendar {code}: {e}", file=sys.stderr)
    return sorted(flagged.items())


def render(rba: list[str], results: list[tuple[str, str]],
           open_deals: list[dict]) -> str:
    """Deterministic HTML. Returns '' when there is genuinely nothing ahead."""
    bits = []
    if rba:
        bits.append(f'<li><strong>RBA decisions:</strong> {" · ".join(rba)}</li>')
    if results:
        named = ", ".join(f"{name} ({code})" if name else code
                          for code, name in results)
        bits.append(
            f'<li><strong>Results flagged (Advance Notice lodged):</strong> '
            f'{named}</li>')
    if open_deals:
        names = []
        for d in open_deals[:6]:
            label = d.get("asset") or d.get("headline", "")
            status = str(d.get("status", "")).replace("_", " ")
            if label:
                names.append(f'{label[:48]} ({status})')
        if names:
            bits.append(f'<li><strong>Deals we are watching resolve:</strong> '
                        f'{"; ".join(names)}</li>')
    if not bits:
        return ""
    return (f'<h2>ON THE HORIZON</h2><ul>{"".join(bits)}</ul>')
