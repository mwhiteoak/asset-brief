"""Market signals strip — cash rate, 10yr bond yield, AUD/USD (RBA statistical
tables, official CSVs) and the A-REIT index daily move (Yahoo Finance chart
API). Every fetch is independent and fail-safe: whatever succeeds renders,
whatever doesn't is silently omitted.
"""

import csv
import io
import sys

import requests

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

# F1 is the daily series. F1.1 is a *monthly average* — using it meant a cash
# rate move could sit unreported in the strip for weeks, which for a property
# brief is the one number you cannot be late on.
RBA_F1 = "https://www.rba.gov.au/statistics/tables/csv/f1-data.csv"
RBA_F2 = "https://www.rba.gov.au/statistics/tables/csv/f2-data.csv"
RBA_F11 = "https://www.rba.gov.au/statistics/tables/csv/f11.1-data.csv"
YAHOO_XPJ = "https://query1.finance.yahoo.com/v8/finance/chart/%5EAXPJ"


def _rba_latest(url: str, keyword: str) -> float | None:
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    rows = list(csv.reader(io.StringIO(r.text)))
    title_row = next(
        (row for row in rows if row and row[0].strip().lower() == "title"), None
    )
    if not title_row:
        return None
    col = next(
        (i for i, c in enumerate(title_row) if keyword.lower() in c.lower()), None
    )
    if col is None:
        return None
    for row in reversed(rows):
        if row and len(row) > col and row[col].strip():
            try:
                return float(row[col])
            except ValueError:
                continue
    return None


def _areit_move() -> float | None:
    r = requests.get(
        YAHOO_XPJ, params={"range": "5d", "interval": "1d"},
        headers=UA, timeout=30,
    )
    r.raise_for_status()
    closes = (
        r.json()["chart"]["result"][0]["indicators"]["quote"][0]["close"]
    )
    closes = [c for c in closes if c is not None]
    if len(closes) < 2:
        return None
    return (closes[-1] / closes[-2] - 1) * 100


def collect() -> list[tuple[str, str]]:
    signals: list[tuple[str, str]] = []
    for label, fn in [
        ("RBA cash rate", lambda: _rba_latest(RBA_F1, "cash rate target")),
        ("AGB 10yr", lambda: _rba_latest(RBA_F2, "10 year")),
    ]:
        try:
            v = fn()
            if v is not None:
                signals.append((label, f"{v:.2f}%"))
        except Exception as e:
            print(f"[warn] signal {label}: {e}", file=sys.stderr)
    try:
        v = _rba_latest(RBA_F11, "usd")
        if v is not None:
            signals.append(("AUD/USD", f"{v:.4f}"))
    except Exception as e:
        print(f"[warn] signal AUD/USD: {e}", file=sys.stderr)
    try:
        v = _areit_move()
        if v is not None:
            signals.append(("A-REITs (XPJ)", f"{v:+.1f}%"))
    except Exception as e:
        print(f"[warn] signal XPJ: {e}", file=sys.stderr)
    return signals
