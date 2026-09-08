"""SQLite access layer + entity resolution.

SQLite (stdlib) rather than DuckDB: after ETL aggregation the working set is
~600 rows and ~75k route rows, which SQLite handles in single-digit
milliseconds. Using the standard library means the whole backend runs with no
pip install at all, which matters more here than columnar speed.
"""
from __future__ import annotations

import difflib
import re
import functools
import json
import os
import sqlite3

from . import config


def get_conn() -> sqlite3.Connection:
    if not os.path.exists(config.DB_PATH):
        raise FileNotFoundError(
            f"No database at {config.DB_PATH}. Run:  python3 -m etl.build"
        )
    con = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def query(sql: str, params: tuple = ()) -> list[dict]:
    con = get_conn()
    try:
        return [dict(r) for r in con.execute(sql, params)]
    finally:
        con.close()


@functools.lru_cache(maxsize=1)
def meta() -> dict:
    try:
        rows = query("SELECT key, value FROM meta")
    except Exception:                                   # noqa: BLE001
        return {}
    return {r["key"]: json.loads(r["value"]) for r in rows}


@functools.lru_cache(maxsize=1)
def _airport_index() -> list[dict]:
    return query(
        "SELECT code, name, city, state, iso_region, type, hub_class, pax "
        "FROM mart_airport_annual"
    )


def get_airport(code: str) -> dict | None:
    rows = query("SELECT * FROM mart_airport_annual WHERE code = ?",
                 (code.strip().upper(),))
    return rows[0] if rows else None


@functools.lru_cache(maxsize=1)
def known_codes() -> frozenset:
    """Every airport code in the mart.

    Cheap (624 rows, cached for the process) and it lets the caller ask the
    data whether a three-letter token is a code, instead of maintaining a
    blacklist of English words by hand.
    """
    return frozenset(r["code"] for r in query("SELECT code FROM mart_airport_annual"))


def code_exists(code: str) -> bool:
    return (code or "").strip().upper() in known_codes()


def list_airports(states: list[str] | None = None,
                  codes: list[str] | None = None,
                  hub_class: str | None = None,
                  min_pax: float | None = None,
                  limit: int = 500) -> list[dict]:
    sql = "SELECT * FROM mart_airport_annual WHERE 1=1"
    params: list = []
    if states:
        sql += f" AND state IN ({','.join('?' * len(states))})"
        params += [s.strip().upper() for s in states]
    if codes:
        sql += f" AND code IN ({','.join('?' * len(codes))})"
        params += [c.strip().upper() for c in codes]
    if hub_class:
        sql += " AND hub_class = ?"
        params.append(hub_class.strip().upper())
    if min_pax is not None:
        sql += " AND pax >= ?"
        params.append(min_pax)
    sql += " ORDER BY pax DESC LIMIT ?"
    params.append(limit)
    return query(sql, tuple(params))


def routes(code: str, year: int | None = None) -> list[dict]:
    m = meta()
    year = year or m.get("window_year")
    return query(
        "SELECT * FROM fact_route_annual WHERE origin = ? AND year = ? "
        "ORDER BY departures DESC",
        (code.strip().upper(), year),
    )


# ---------------------------------------------------------------- resolution
def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 .]", " ", (text or "").lower()).strip()


def resolve_region(text: str) -> tuple[list[str] | None, str | None]:
    """Map a region phrase to state codes.

    Matching is deliberately one-directional and word-boundary aware. The old
    version also tested `phrase in key`, so a short word became a substring of
    a longer key and silently expanded into the wrong place: "west" matched
    "midwest" and returned Ohio, "east" matched "northeast". A confidently
    wrong region is far worse than no match, because the caller cannot tell.
    """
    states, label, _ = resolve_region_scored(text)
    return states, label


def resolve_region_scored(text: str) -> tuple[list[str] | None, str | None, str]:
    """As resolve_region, but also reports how it matched.

    Returns (states, label, confidence) where confidence is "exact", "phrase",
    "fuzzy" or "none", so a caller can say "I read that as the West" rather
    than pretending certainty.
    """
    t = _norm(text)
    if not t:
        return None, None, "none"

    if t in config.REGIONS:
        return config.REGIONS[t], t, "exact"

    # Whole-word match of a known key inside a longer phrase, longest first so
    # "west coast" wins over "west".
    for name in sorted(config.REGIONS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(name)}\b", t):
            return config.REGIONS[name], name, "phrase"

    close = difflib.get_close_matches(t, list(config.REGIONS), n=1, cutoff=0.85)
    if close:
        return config.REGIONS[close[0]], close[0], "fuzzy"
    return None, None, "none"


# Two-letter state codes that are also ordinary English words. The branch
# below only ever fires on a message that is nothing BUT the two letters, so
# "ok" reached it as a bare acknowledgement and came back as Oklahoma -- which
# then also carried the message past the scope guard, because _looks_aviation
# treats any resolved place as evidence the question is in scope.
AMBIGUOUS_TWO_LETTER = {"ok", "or", "in", "me", "hi", "oh", "la",
                        "de", "id", "pa", "ma", "al", "ar"}


def resolve_state(text: str) -> tuple[str | None, str | None]:
    """Map a state name (or two-letter code) to its code. Word-boundary safe."""
    t = _norm(text)
    if not t:
        return None, None
    if t in config.US_STATES:
        return config.US_STATES[t], t
    up = t.upper()
    if len(up) == 2 and up in set(config.US_STATES.values()):
        if t in AMBIGUOUS_TWO_LETTER:
            return None, None
        return up, up
    for name in sorted(config.US_STATES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(name)}\b", t):
            return config.US_STATES[name], name
    close = difflib.get_close_matches(t, list(config.US_STATES), n=1, cutoff=0.88)
    if close:
        return config.US_STATES[close[0]], close[0]
    return None, None


def resolve_metro(text: str) -> tuple[list[str] | None, str | None]:
    t = _norm(text)
    for alias, target in config.METRO_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", t):
            return config.METRO_GROUPS[target], target
    for name in sorted(config.METRO_GROUPS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(name)}\b", t):
            return config.METRO_GROUPS[name], name
    return None, None


# Words that mean "somewhere" without naming it. If one of these is present and
# nothing resolves, the question had a place in it that we failed to understand,
# and we must say so instead of quietly answering about the whole country.
PLACE_HINTS = ("region", "area", "state", "coast", "part of the country",
               "midwest", "north", "south", "east", "west", "near", "around",
               "in the")


def resolve_place(text: str) -> dict:
    """Resolve free text to a place of any kind.

    Tries region, then state, then metro, then a specific airport, and reports
    which kind matched. `looks_like_place` is the important one: it tells the
    caller that the user named somewhere even when we could not resolve it.
    """
    t = _norm(text)
    states, label, conf = resolve_region_scored(t)
    if states:
        return {"kind": "region", "label": label, "states": states,
                "confidence": conf, "looks_like_place": True}

    code, name = resolve_state(t)
    if code:
        return {"kind": "state", "label": name, "states": [code],
                "confidence": "exact", "looks_like_place": True}

    metro, mlabel = resolve_metro(t)
    if metro:
        return {"kind": "metro", "label": mlabel, "codes": metro,
                "confidence": "exact", "looks_like_place": True}

    hits = score_airport_match(t)
    if hits and hits[0][0] >= 0.90:
        a = hits[0][1]
        return {"kind": "airport", "label": a["code"], "codes": [a["code"]],
                "confidence": "exact", "looks_like_place": True}

    return {"kind": None, "label": None, "confidence": "none",
            "looks_like_place": any(h in t for h in PLACE_HINTS)}


def known_places(limit: int = 14) -> list[str]:
    """A short, human list for 'here is what I do understand'."""
    return sorted(config.REGIONS)[:limit]


def score_airport_match(text: str) -> list[tuple[float, dict]]:
    """Score airports against free text. Returns (score, airport) desc.

    Scoring is deliberately conservative. A loose fuzzy threshold produced
    nonsense on short spans -- "boston" matched Charleston, "logan" matched
    an unrelated field -- so exact code and substring matches are scored well
    above fuzzy ones, and weak fuzzy matches are discarded entirely.
    """
    t = (text or "").strip()
    if not t:
        return []
    idx = _airport_index()
    up, tl = t.upper(), t.lower()
    scored: list[tuple[float, dict]] = []

    for a in idx:
        name = (a.get("name") or "").lower()
        city = (a.get("city") or "").lower()
        size_bonus = min(0.05, (a.get("pax") or 0) / 2e9)

        if a["code"] == up:
            scored.append((1.0, a))
            continue
        # whole-word hit inside the airport or city name
        if re.search(rf"\b{re.escape(tl)}\b", name) or re.search(rf"\b{re.escape(tl)}\b", city):
            scored.append((0.90 + size_bonus, a))
            continue
        if len(tl) >= 4 and (tl in name or tl in city):
            scored.append((0.80 + size_bonus, a))
            continue
        ratio = max(difflib.SequenceMatcher(None, tl, name).ratio(),
                    difflib.SequenceMatcher(None, tl, city).ratio())
        # Only trust fuzzy matches that are genuinely close.
        if ratio >= 0.78:
            scored.append((ratio * 0.75 + size_bonus, a))

    scored.sort(key=lambda s: (-s[0], -(s[1].get("pax") or 0)))
    return scored


def resolve_airport(text: str, limit: int = 5) -> list[dict]:
    """Fuzzy-resolve free text to airports.

    Handles what users actually type -- and say, once voice is on: an IATA
    code, an airport or city name, and colloquial names like "Logan". Returns
    ranked candidates rather than guessing, so the agent can ask one
    clarifying question when the answer is genuinely ambiguous.
    """
    return [a for _, a in score_airport_match(text)[:limit]]
