"""TinyFish free Search + Fetch for Eve (installed 2026-09-30; see tools.py).

Target path: ~/soveryn_vnext/soveryn/platform/web/tinyfish.py (Soveryn tower).
Only two hosts are ever contacted; Agent/Browser/Research/Monitor (wallet-metered)
are unreachable from this code by construction. Local caps stay under the free
tier (Search 500/hr, Fetch 1,000 URLs/day) so Eve can't run into any metered path.
"""
from __future__ import annotations

import json, os, threading, time, urllib.error, urllib.parse, urllib.request
from collections import deque

SEARCH_URL = "https://api.search.tinyfish.ai"   # GET, free
FETCH_URL = "https://api.fetch.tinyfish.ai"     # POST, free
_ALLOWED = frozenset({SEARCH_URL, FETCH_URL})

SEARCH_CAP_PER_HOUR = int(os.environ.get("SOVERYN_TINYFISH_SEARCH_PER_HOUR", "400"))
FETCH_CAP_PER_DAY = int(os.environ.get("SOVERYN_TINYFISH_FETCH_PER_DAY", "800"))


class TinyFishError(RuntimeError):
    pass


def api_key() -> str:
    return (os.environ.get("TINYFISH_API_KEY") or "").strip().strip('"').strip("'")


class _Window:
    def __init__(self, cap: int, seconds: int):
        self.cap, self.seconds, self.hits, self.lock = cap, seconds, deque(), threading.Lock()

    def take(self, n: int = 1) -> bool:
        now = time.time()
        with self.lock:
            while self.hits and now - self.hits[0] > self.seconds:
                self.hits.popleft()
            if len(self.hits) + n > self.cap:
                return False
            self.hits.extend([now] * n)
            return True


_search_win = _Window(SEARCH_CAP_PER_HOUR, 3600)
_fetch_win = _Window(FETCH_CAP_PER_DAY, 86400)


def _call(url: str, *, data: bytes | None = None, timeout: float) -> dict:
    base = url.split("?", 1)[0].rstrip("/")
    if base not in _ALLOWED:  # hard guard: never any wallet endpoint
        raise TinyFishError(f"host not allowlisted: {base}")
    key = api_key()
    if not key:
        raise TinyFishError("TINYFISH_API_KEY not set")
    headers = {"X-API-Key": key, "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raise TinyFishError(f"HTTP {e.code}") from None  # never echo key/body
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise TinyFishError(f"network: {e}") from None


def search(query: str, *, max_results: int = 5, timeout: float = 15.0) -> list[dict]:
    if not _search_win.take():
        raise TinyFishError("local search cap reached")
    q = urllib.parse.urlencode({"query": query.strip(), "location": "US", "language": "en"})
    payload = _call(f"{SEARCH_URL}?{q}", timeout=timeout)
    out = []
    for r in (payload.get("results") or [])[:max_results]:
        out.append({"title": r.get("title") or "", "url": r.get("url") or "",
                    "snippet": r.get("snippet") or "", "source": "tinyfish"})
    return out


def fetch(url: str, *, max_chars: int = 8000, timeout: float = 150.0) -> dict:
    if not _fetch_win.take(1):
        raise TinyFishError("local fetch cap reached")
    body = json.dumps({"urls": [url], "format": "markdown", "per_url_timeout_ms": 45000}).encode()
    payload = _call(FETCH_URL, data=body, timeout=timeout)
    if payload.get("errors"):
        raise TinyFishError(f"fetch error: {payload['errors'][0].get('error')}")
    res = (payload.get("results") or [{}])[0]
    text = res.get("text") or ""
    return {"url": res.get("final_url") or res.get("url") or url, "title": res.get("title") or "",
            "content": text[:max_chars], "truncated": len(text) > max_chars}
