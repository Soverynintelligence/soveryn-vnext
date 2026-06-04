"""Web search + fetch tools for Aetheria and Vett.

Sovereign-by-default: search hits a local SearXNG instance (no third-party
API keys), fetch uses trafilatura for main-content extraction (no remote
service). SSRF guard rejects private/loopback/link-local IPs so a model
that's been given a URL can't be tricked into hitting localhost services.

Public surface: register_web_tools(registry, *, searxng_url, owner_agent).
"""

from __future__ import annotations

from soveryn.platform.web.fetch import (
    FetchError,
    SSRFError,
    fetch_and_extract,
)
from soveryn.platform.web.search import (
    SearchError,
    SearchResult,
    search_via_searxng,
)
from soveryn.platform.web.tools import (
    build_fetch_url_tool,
    build_web_search_tool,
    register_web_tools,
)

__all__ = [
    "FetchError",
    "SSRFError",
    "SearchError",
    "SearchResult",
    "build_fetch_url_tool",
    "build_web_search_tool",
    "fetch_and_extract",
    "register_web_tools",
    "search_via_searxng",
]
