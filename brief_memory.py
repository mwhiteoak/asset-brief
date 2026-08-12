"""Persistent memory for the brief — a JSON deal/story log committed back to
the repo after each edition.

Powers:
  - dedup ("don't repeat what ran in the last 14 days")
  - the deal tracker ("Casuarina asset went to LOI 3 weeks ago — any update?")
  - the Friday Week in Review table
  - a growing private transactions database (query it yourself anytime)
"""

import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.abspath(__file__))
# Editions are dated in Brisbane time, so the cutoffs have to be too. The
# workflow runs at 19:30 UTC, which is already the next day in Brisbane —
# a naive now() here puts every window a day out.
TIMEZONE = ZoneInfo("Australia/Brisbane")
MEMORY_PATH = os.path.join(ROOT, "data", "memory.json")

OPEN_STATUSES = {"on_market", "loi", "due_diligence"}
DEAL_STATUSES = OPEN_STATUSES | {"sold"}
RETENTION_DAYS = 550  # ~18 months


def load() -> dict:
    try:
        with open(MEMORY_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"items": []}


def save(mem: dict) -> None:
    os.makedirs(os.path.dirname(MEMORY_PATH), exist_ok=True)
    with open(MEMORY_PATH, "w") as f:
        json.dump(mem, f, indent=2, ensure_ascii=False)


def _since(days: int) -> str:
    return (datetime.now(TIMEZONE) - timedelta(days=days)).strftime("%Y-%m-%d")


def recent_headlines(mem: dict, days: int = 14) -> list[dict]:
    cutoff = _since(days)
    return [
        {"date": i.get("date", ""), "headline": i.get("headline", ""),
         "url": i.get("url", "")}
        for i in mem["items"] if i.get("date", "") >= cutoff
    ]


def open_deals(mem: dict, days: int = 120) -> list[dict]:
    """Deals last seen in an unresolved state — the tracker checks on these."""
    cutoff = _since(days)
    latest: dict[str, dict] = {}
    for i in mem["items"]:
        key = (i.get("asset") or i.get("headline", "")).lower()[:80]
        if key and i.get("date", "") >= cutoff:
            if key not in latest or i["date"] > latest[key]["date"]:
                latest[key] = i
    return [i for i in latest.values() if i.get("status") in OPEN_STATUSES]


def week_deals(mem: dict, days: int = 7) -> list[dict]:
    cutoff = _since(days)
    return [
        i for i in mem["items"]
        if i.get("date", "") >= cutoff and i.get("status") in DEAL_STATUSES
    ]


def append(mem: dict, records: list[dict], edition_date: str) -> None:
    for r in records:
        if not isinstance(r, dict) or not r.get("headline"):
            continue
        r["date"] = edition_date
        mem["items"].append(r)
    cutoff = _since(RETENTION_DAYS)
    mem["items"] = [i for i in mem["items"] if i.get("date", "") >= cutoff]
