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
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.abspath(__file__))
# Editions are dated in Brisbane time, so the cutoffs have to be too. The
# workflow runs at 19:30 UTC, which is already the next day in Brisbane —
# a naive now() here puts every window a day out.
TIMEZONE = ZoneInfo("Australia/Brisbane")
MEMORY_PATH = os.path.join(ROOT, "data", "memory.json")


def path_for(name: str | None = None) -> str:
    """Each edition keeps its own store so their dedup histories stay separate —
    the franchise weekly must not suppress a story because the property daily
    ran something adjacent."""
    return MEMORY_PATH if not name else os.path.join(
        ROOT, "data", f"memory_{name}.json")

OPEN_STATUSES = {"on_market", "loi", "due_diligence"}
DEAL_STATUSES = OPEN_STATUSES | {"sold"}
RETENTION_DAYS = 550  # ~18 months


def load(path: str | None = None) -> dict:
    try:
        with open(path or MEMORY_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"items": []}


def save(mem: dict, path: str | None = None) -> None:
    path = path or MEMORY_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
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


def _story_key(text: str) -> str:
    """Normalise a headline so the same story from two outlets collides.

    'Cbus pays $1.3b for half of Carindale' and 'Lendlease sells Carindale
    stake to Cbus for $1.3bn' should be recognised as one story. Stripping
    filler words and keeping the distinctive tokens gets most of the way
    there without needing anything cleverer.
    """
    return " ".join(sorted(_tokens(text)))


# Words too common in property headlines to identify a story.
_STOP = {
    "the", "a", "an", "for", "to", "of", "in", "on", "at", "and", "with", "as",
    "its", "after", "from", "by", "is", "are", "has", "have", "new", "says",
    "amid", "over", "australian", "australia", "property", "properties",
    "million", "billion", "per", "cent", "deal", "deals", "buys", "sells",
    "sale", "sold", "market", "centre", "center", "group", "portfolio",
    "asset", "assets", "into", "out", "up", "down", "first", "back",
    # Generic property descriptors. These identify a CATEGORY, not a story —
    # without them two unrelated Coles centres matched on "coles anchored".
    "anchored", "anchor", "shopping", "retail", "office", "industrial",
    "childcare", "logistics", "commercial", "fund", "funds", "credit", "reit",
    "trust", "hits", "secures", "launches", "lists", "listed", "plans",
    "yield", "cap", "rate", "investor", "investors", "landlord", "tenant",
}


def _tokens(text: str) -> set:
    t = re.sub(r"[^a-z0-9 ]", " ", str(text or "").lower())
    # Reporting-period markers are shared by every announcement in a season
    # (fy26, 1h26, q3) and identify a calendar slot, not a story.
    t = re.sub(r"\b(fy|h[12]|q[1-4]|1h|2h)\s?\d{2,4}\b", " ", t)
    return {w for w in t.split() if w not in _STOP and len(w) > 2}


def same_story(a: str, b: str) -> bool:
    """Do two headlines describe the same story?

    Exact key matching failed the real case: 'Cbus pays $1.3b for half of
    Westfield Carindale' and 'Lendlease sells Carindale stake to Cbus' share
    only two words out of nine. But those two words are 'carindale' and
    'cbus' — the distinctive ones — which is exactly the signal that matters.
    So: match on shared distinctive tokens, not on the whole string.

    Two shared tokens is the floor; one is not enough (every Coles story
    would collide with every other Coles story).
    """
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    shared = ta & tb
    # The floor of two shared distinctive tokens does the real work; the ratio
    # only guards against long headlines colliding by chance. Kept deliberately
    # loose because the costs are asymmetric — a false positive merely FLAGS a
    # story (the editor may still run it as an update), while only an exact URL
    # match is dropped outright. Missing a repeat is worse than over-flagging.
    return len(shared) >= 2 and len(shared) / min(len(ta), len(tb)) >= 0.25


def published(mem: dict, days: int = 21) -> tuple[set, set]:
    """(urls, story keys) already sent to readers in the last `days`.

    This is what makes cross-edition de-duplication enforceable in code
    rather than merely requested of the editor. A daily email that repeats
    itself gets unsubscribed from, and the prompt-level "don't repeat"
    instruction cannot catch the same story reported by a second outlet
    under a different headline.
    """
    cutoff = _since(days)
    urls, headlines = set(), []
    for i in mem.get("items", []):
        if i.get("date", "") < cutoff:
            continue
        if i.get("url"):
            urls.add(re.sub(r"^https?://(www\.)?", "",
                            str(i["url"]).lower()).rstrip("/"))
        h = i.get("headline") or i.get("asset") or ""
        if h:
            headlines.append(h)
    return urls, headlines


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
