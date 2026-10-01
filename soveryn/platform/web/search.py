"""House web search: Brave Search API first, local SearXNG as fallback.

Stdlib-only (urllib). The Brave HTML scraper behind SearXNG is captcha'd
from this IP; the official API (`X-Subscription-Token`) is not. Key lives
in `~/soveryn_vnext/.env` as `BRAVE_SEARCH_API_KEY` — never log it.
"""

from __future__ import annotations

import json
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

BRAVE_WEB_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


class SearchError(RuntimeError):
    """Raised when the SearXNG call fails or returns an unexpected shape."""


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    engine: str


# 2026-09-07: Brave is still the quality engine from this IP when it answers,
# but Brave Search flags the house as a bot (HTTP 429 + captcha). Pinning
# agents to Brave-only then yields 0 hits and Scout looks dead. Ask Brave
# and Bing; keep Brave results when present, fall through to Bing when
# SearXNG suspends Brave. Do not add DDG/Qwant/Startpage — they CAPTCHA
# this IP and only add suspend noise.
DEFAULT_ENGINES = "brave,bing"

# Over-fetch before ranking. Bing's first hits are often the first query
# token (Pinehurst Resort for "Pinehurst pond installer").
_RAW_RESULT_CAP = 30

_TOKEN = re.compile(r"[a-z0-9]{2,}")
_STOP = frozenset(
    {
        "the",
        "and",
        "for",
        "of",
        "to",
        "in",
        "a",
        "an",
        "on",
        "with",
        "from",
        "by",
        "or",
        "is",
        "at",
        "as",
        "be",
        "it",
        "vs",
        "www",
        "http",
        "https",
        "com",
        "org",
        "net",
        "html",
    }
)

# Agent search is not a dictionary. Drop these even if an engine ranks them first.
_DICTIONARY_HOST_MARKERS = (
    "merriam-webster.com",
    "dictionary.com",
    "cambridge.org/dictionary",
    "thefreedictionary.com",
    "wiktionary.org",
    "vocabulary.com",
)

# Brand/ads junk Bing returns from this IP when Brave is suspended (2026-09).
_JUNK_HOST_MARKERS = (
    "on.com",
    "onnicotine.com",
    "americanexpress.com",
    "carolinaherrera.com",
    "carolinashoe.com",
    "koihappiness.com",
    "koiautoparts.com",
    "itexamanswers.net",
)


@dataclass(frozen=True)
class SearchResponse:
    results: tuple[SearchResult, ...]
    unresponsive_engines: tuple[tuple[str, str], ...] = ()


def _brave_api_key() -> str:
    raw = os.environ.get("BRAVE_SEARCH_API_KEY") or os.environ.get("BRAVE_API_KEY") or ""
    return raw.strip().strip('"').strip("'")


def search_web(
    query: str,
    *,
    searxng_url: str,
    max_results: int = 5,
    timeout: float = 10.0,
    engines: str | None = DEFAULT_ENGINES,
) -> tuple[SearchResult, ...]:
    """Brave Search API when a key is present; SearXNG (Brave+Bing) otherwise.

    A Brave API failure (auth, 429, empty) falls through to SearXNG so Scout
    still gets *something* rather than a dead tool.
    """
    key = _brave_api_key()
    if key:
        try:
            hits = search_via_brave_api(
                query, api_key=key, max_results=max_results, timeout=timeout
            )
            if hits:
                return hits
        except SearchError:
            pass
    return search_via_searxng(
        query,
        searxng_url=searxng_url,
        max_results=max_results,
        timeout=timeout,
        engines=engines,
    )


def search_via_brave_api(
    query: str,
    *,
    api_key: str,
    max_results: int = 5,
    timeout: float = 10.0,
) -> tuple[SearchResult, ...]:
    """Official Brave Search API. Does not scrape search.brave.com."""
    if not isinstance(query, str) or not query.strip():
        raise SearchError("query must be a non-empty string")
    if max_results <= 0:
        raise SearchError("max_results must be positive")
    if not api_key.strip():
        raise SearchError("Brave Search API key is empty")

    count = max(1, min(int(max_results), 20))
    url = (
        BRAVE_WEB_SEARCH_URL
        + "?"
        + urllib.parse.urlencode({"q": query.strip(), "count": str(count)})
    )
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "soveryn-vnext/0 (+local)",
            "X-Subscription-Token": api_key.strip(),
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            status = resp.status
    except urllib.error.HTTPError as e:
        # Free tier is 1 QPS. One short retry covers Scout/agent double-taps.
        if e.code == 429:
            time.sleep(1.1)
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
                    status = resp.status
            except urllib.error.HTTPError as e2:
                raise SearchError(f"Brave API returned HTTP {e2.code}") from e2
        else:
            raise SearchError(f"Brave API returned HTTP {e.code}") from e
    except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
        raise SearchError(f"Brave API unreachable: {type(e).__name__}") from e
    if not (200 <= status < 300):
        raise SearchError(f"Brave API returned non-2xx: {status}")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SearchError(f"Brave API response was not JSON: {e}") from e
    parsed = _parse_brave_web(payload, max_results=max(_RAW_RESULT_CAP, max_results))
    return _rank_results(query.strip(), parsed, max_results=max_results)


def _parse_brave_web(payload: Any, *, max_results: int) -> tuple[SearchResult, ...]:
    if not isinstance(payload, dict):
        raise SearchError("unexpected Brave API shape: top-level not a dict")
    web = payload.get("web")
    if not isinstance(web, dict):
        return ()
    raw_results = web.get("results")
    if not isinstance(raw_results, list):
        return ()
    out: list[SearchResult] = []
    for item in raw_results:
        if len(out) >= max_results:
            break
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        title = item.get("title")
        if not isinstance(url, str) or not isinstance(title, str):
            continue
        snippet = item.get("description") or item.get("extra_snippets") or ""
        if isinstance(snippet, list):
            snippet = " ".join(str(s) for s in snippet if s)
        if not isinstance(snippet, str):
            snippet = str(snippet)
        if _is_dictionary_url(url):
            continue
        out.append(
            SearchResult(
                title=title.strip(),
                url=url.strip(),
                snippet=snippet.strip(),
                engine="brave-api",
            )
        )
    return tuple(out)


def search_via_searxng(
    query: str,
    *,
    searxng_url: str,
    max_results: int = 5,
    timeout: float = 10.0,
    engines: str | None = DEFAULT_ENGINES,
) -> tuple[SearchResult, ...]:
    """Hit SearXNG's JSON API and return at most `max_results` parsed results.

    Raises SearchError on connection failure, non-2xx response, JSON parse
    failure, unexpected schema, or zero hits when engines report failures.
    The caller's tool handler should map SearchError into a structured error.
    """
    resp = search_via_searxng_detailed(
        query,
        searxng_url=searxng_url,
        max_results=max_results,
        timeout=timeout,
        engines=engines,
    )
    if resp.results:
        return resp.results
    if resp.unresponsive_engines:
        detail = "; ".join(f"{n}: {why}" for n, why in resp.unresponsive_engines[:6])
        raise SearchError(
            f"SearXNG returned 0 results; engines unresponsive: {detail}"
        )
    raise SearchError("SearXNG returned 0 results (no engine errors reported)")


def search_via_searxng_detailed(
    query: str,
    *,
    searxng_url: str,
    max_results: int = 5,
    timeout: float = 10.0,
    engines: str | None = DEFAULT_ENGINES,
) -> SearchResponse:
    """Like search_via_searxng but keeps unresponsive_engines metadata."""
    if not isinstance(query, str) or not query.strip():
        raise SearchError("query must be a non-empty string")
    if max_results <= 0:
        raise SearchError("max_results must be positive")

    base = searxng_url.rstrip("/")
    params: dict[str, str] = {
        "q": query.strip(),
        "format": "json",
    }
    if engines:
        params["engines"] = engines
    url = f"{base}/search?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "soveryn-vnext/0 (+local)"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            status = resp.status
    except urllib.error.HTTPError as e:
        raise SearchError(f"SearXNG returned HTTP {e.code}: {e.reason}") from e
    except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
        raise SearchError(f"SearXNG unreachable: {e}") from e
    if not (200 <= status < 300):
        raise SearchError(f"SearXNG returned non-2xx: {status}")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        # Most likely cause: JSON format not enabled in SearXNG settings.yml.
        raise SearchError(
            f"SearXNG response was not JSON (is `json` in settings.search.formats?): {e}"
        ) from e
    raw = _parse_results(payload, max_results=max(_RAW_RESULT_CAP, max_results))
    results = _rank_results(query.strip(), raw, max_results=max_results)
    unresp = _parse_unresponsive(payload)
    return SearchResponse(results=results, unresponsive_engines=unresp)


def _parse_unresponsive(payload: Any) -> tuple[tuple[str, str], ...]:
    raw = payload.get("unresponsive_engines") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        return ()
    out: list[tuple[str, str]] = []
    for item in raw:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            out.append((str(item[0]), str(item[1])))
        elif isinstance(item, str):
            out.append((item, "unresponsive"))
    return tuple(out)


def _parse_results(payload: Any, *, max_results: int) -> tuple[SearchResult, ...]:
    if not isinstance(payload, dict):
        raise SearchError(f"unexpected response shape: top-level not a dict")
    raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        raise SearchError("unexpected response shape: 'results' missing or not a list")
    out: list[SearchResult] = []
    for item in raw_results:
        if len(out) >= max_results:
            break
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        title = item.get("title")
        if not isinstance(url, str) or not isinstance(title, str):
            continue
        snippet = item.get("content") or ""
        if not isinstance(snippet, str):
            snippet = str(snippet)
        engine = item.get("engine") or ""
        if not isinstance(engine, str):
            engine = str(engine)
        if _is_dictionary_url(url):
            continue
        out.append(SearchResult(
            title=title.strip(),
            url=url.strip(),
            snippet=snippet.strip(),
            engine=engine.strip(),
        ))
    return tuple(out)


def _is_dictionary_url(url: str) -> bool:
    host = url.lower()
    if any(marker in host for marker in _DICTIONARY_HOST_MARKERS):
        return True
    return any(marker in host for marker in _JUNK_HOST_MARKERS)


def _tokens(text: str) -> frozenset[str]:
    return frozenset(t for t in _TOKEN.findall(text.lower()) if t not in _STOP)


def _rank_results(
    query: str,
    results: tuple[SearchResult, ...],
    *,
    max_results: int,
) -> tuple[SearchResult, ...]:
    """Prefer hits that share query terms; prefer Brave when scores tie.

    Returns at most `max_results`. If overlap filtering would empty the
    list, keep the original (still junk-host-filtered) order so a weird
    Bing page is better than telling Scout the internet is down.
    """
    if not results or max_results <= 0:
        return ()
    qtok = _tokens(query)
    long = {t for t in qtok if len(t) >= 4}
    scored: list[tuple[int, int, int, SearchResult]] = []
    for i, r in enumerate(results):
        blob = _tokens(f"{r.title} {r.snippet} {r.url}")
        matched = qtok & blob
        # Length-weighted so "searxng" beats a stray "open" on a tennis page.
        overlap = sum(len(t) for t in matched) if qtok else 0
        if long and not (long & blob):
            overlap = 0
        brave = 1 if r.engine.strip().lower() == "brave" else 0
        scored.append((overlap, brave, -i, r))
    scored.sort(reverse=True)
    min_overlap = 1 if len(qtok) >= 2 else 0
    picked = [r for overlap, _b, _i, r in scored if overlap >= min_overlap]
    if not picked:
        picked = [r for _o, _b, _i, r in scored]
    return tuple(picked[:max_results])
