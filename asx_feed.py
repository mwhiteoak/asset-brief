"""Pull price-sensitive ASX announcements for the ticker universe.

Uses the Markit Digital API that powers asx.com.au's company announcement
pages (e.g. https://www.asx.com.au/markets/trade-our-cash-market/announcements.col
for Coles). Each announcement links directly to its PDF via the ASX CDN, with
the company's announcements page as a secondary link.

Every ticker is fetched individually with a polite delay; any single failure
is logged and skipped so one blocked request never kills the edition.
"""

import re
import sys
import time
from datetime import datetime, timezone

import requests

API = ("https://asx.api.markitdigital.com/asx-research/1.0/"
       "companies/{code}/announcements")
PDF = ("https://cdn-api.markitdigital.com/apiman-gateway/ASX/"
       "asx-research/1.0/file/{key}")
PAGE = ("https://www.asx.com.au/markets/trade-our-cash-market/"
        "announcements.{code_lower}")
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json",
}
BRISBANE_UTC_OFFSET = 10  # hours, no DST


def tidy_name(raw: str) -> str:
    """'COLES GROUP LIMITED' -> 'Coles Group'. The API shouts and appends a
    legal suffix; neither belongs in an email."""
    name = (raw or "").strip()
    if not name:
        return ""
    if name.isupper():
        name = name.title()
    # Keep 'Group', 'REIT' etc., drop the company-type suffix.
    name = re.sub(r"[,\s]+(Limited|Ltd|Pty|Plc)\.?$", "", name,
                  flags=re.IGNORECASE).strip()
    # The API title-cases these awkwardly.
    for wrong, right in (("Reit", "REIT"), ("Gpt", "GPT"), ("Bwp", "BWP"),
                         ("Hmc", "HMC"), ("Jb Hi-Fi", "JB Hi-Fi")):
        name = re.sub(rf"\b{wrong}\b", right, name)
    return name


def price_sensitive(tickers: list[str], since: datetime) -> list[dict]:
    """Return price-sensitive announcements released after `since` (tz-aware)."""
    since_utc = since.astimezone(timezone.utc)
    items: list[dict] = []
    for code in tickers:
        code = code.strip().upper()
        try:
            r = requests.get(
                API.format(code=code),
                params={"itemsPerPage": 15},
                headers=HEADERS,
                timeout=25,
            )
            if r.status_code != 200:
                print(f"[warn] ASX {code}: HTTP {r.status_code}", file=sys.stderr)
                continue
            data = r.json().get("data", {})
            company = tidy_name(data.get("displayName", ""))
            for a in data.get("items", []):
                if not a.get("isPriceSensitive"):
                    continue
                raw = a.get("date", "")
                try:
                    released = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if released < since_utc:
                    continue
                key = a.get("documentKey", "")
                local = released.astimezone(
                    timezone.utc).timestamp() + BRISBANE_UTC_OFFSET * 3600
                released_local = datetime.fromtimestamp(
                    local, tz=timezone.utc)
                items.append({
                    "code": code,
                    # Carried through so the email can say "Coles Group (COL)"
                    # rather than making the reader decode 37 ticker symbols.
                    "company": company,
                    "header": (a.get("headline") or "").strip(),
                    "url": PDF.format(key=key) if key
                           else PAGE.format(code_lower=code.lower()),
                    "page_url": PAGE.format(code_lower=code.lower()),
                    "released": released_local.strftime(
                        "%a %d %b, %I:%M%p AEST"),
                    "released_iso": released.isoformat(),
                })
        except Exception as e:
            print(f"[warn] ASX {code}: {e}", file=sys.stderr)
        time.sleep(0.4)  # be polite

    items.sort(key=lambda x: x["released_iso"], reverse=True)
    return items
