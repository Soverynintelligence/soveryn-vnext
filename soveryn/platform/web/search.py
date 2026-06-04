"""SearXNG metasearch client.

Stdlib-only (urllib). Talks to a local SearXNG instance over HTTP and
returns a typed list of results. The instance is assumed to have
`json` enabled in `search.formats` — that's the default in our
settings.yml. If it's not, the JSON parse will raise SearchError.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


class SearchError(RuntimeError):
    """Raised when the SearXNG call fails or returns an unexpected shape."""


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    engine: str


def search_via_searxng(
    query: str,
    *,
    searxng_url: str,
    max_results: int = 5,
    timeout: float = 10.0,
) -> tuple[SearchResult, ...]:
    """Hit SearXNG's JSON API and return at most `max_results` parsed results.

    Raises SearchError on connection failure, non-2xx response, JSON parse
    failure, or unexpected schema. The caller's tool handler should map
    SearchError into a structured error result for the agent.
    """
    if not isinstance(query, str) or not query.strip():
        raise SearchError("query must be a non-empty string")
    if max_results <= 0:
        raise SearchError("max_results must be positive")

    base = searxng_url.rstrip("/")
    params = urllib.parse.urlencode({
        "q": query.strip(),
        "format": "json",
    })
    url = f"{base}/search?{params}"
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
    return _parse_results(payload, max_results=max_results)


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
        out.append(SearchResult(
            title=title.strip(),
            url=url.strip(),
            snippet=snippet.strip(),
            engine=engine.strip(),
        ))
    return tuple(out)
