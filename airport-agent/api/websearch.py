"""Web retrieval for announced airport capital programmes.

Deliberately narrow. This exists to answer one kind of question the local data
genuinely cannot: *what has this airport said it is going to build?* Announced
terminal programmes, master plans and funding awards are news, and news does
not belong in a deterministic score.

So the contract is strict:
  * qualitative only, extractive snippets with citations, no computed figures;
  * never read by anything in api/scoring/;
  * the query is built server-side from a template, never from the user's raw
    text, which keeps both the scope and the injection surface small;
  * absent an API key it returns `unavailable` rather than failing, and the
    caller falls back to the curated constraints file.

Providers are tried in config order. All speak plain HTTP through urllib, so
the backend still needs no third-party packages.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from . import config

TIMEOUT = 8          # a hung search must not hang the answer
MAX_SNIPPET = 280    # long enough to be useful, short enough to bound injection


def _post_json(url: str, payload: dict, headers: dict) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())


def _get_json(url: str, headers: dict) -> dict:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())


def _clean(text: str) -> str:
    return " ".join((text or "").split())[:MAX_SNIPPET]


def _publisher(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).netloc.replace("www.", "")
    except Exception:                                      # noqa: BLE001
        return "unknown"


def _tavily(query: str, n: int) -> list[dict]:
    data = _post_json("https://api.tavily.com/search",
                      {"api_key": config.TAVILY_API_KEY, "query": query,
                       "max_results": n, "search_depth": "basic"}, {})
    return [{"title": r.get("title", ""), "url": r.get("url", ""),
             "claim": _clean(r.get("content", "")),
             "published": r.get("published_date"),
             "publisher": _publisher(r.get("url", ""))}
            for r in (data.get("results") or [])]


def _brave(query: str, n: int) -> list[dict]:
    url = ("https://api.search.brave.com/res/v1/web/search?"
           + urllib.parse.urlencode({"q": query, "count": n}))
    data = _get_json(url, {"X-Subscription-Token": config.BRAVE_API_KEY,
                           "Accept": "application/json"})
    return [{"title": r.get("title", ""), "url": r.get("url", ""),
             "claim": _clean(r.get("description", "")),
             "published": r.get("age"),
             "publisher": _publisher(r.get("url", ""))}
            for r in ((data.get("web") or {}).get("results") or [])]


def search(query: str, max_results: int = 5) -> dict:
    """Run one search. Never raises: failure is a reported state, not a crash."""
    provider = config.search_provider()
    if provider == "none":
        return {"provider": "none", "findings": [],
                "unavailable": "no search provider configured"}
    try:
        findings = (_tavily if provider == "tavily" else _brave)(query, max_results)
        return {"provider": provider, "findings": findings, "unavailable": None}
    except urllib.error.HTTPError as exc:
        return {"provider": provider, "findings": [],
                "unavailable": f"search returned HTTP {exc.code}"}
    except Exception as exc:                               # noqa: BLE001
        return {"provider": provider, "findings": [],
                "unavailable": f"search failed: {exc}"}
