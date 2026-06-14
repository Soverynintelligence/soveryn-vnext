"""Web search + fetch tool factories.

Two tools per agent:
  - web_search(query, max_results=5) → list of {title, url, snippet, engine}
  - fetch_url(url, max_chars=8000) → {title, content, truncated, url}

Both tools are registered owner-keyed; current owners are Aetheria and Vett.
Scotty deliberately does NOT get them (his surface is mechanical local-host
tools, not arbitrary outbound network).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from soveryn.platform.tools.registry import ToolArgError, ToolRegistry, ToolSpec
from soveryn.platform.web.fetch import (
    DEFAULT_MAX_CHARS,
    FetchError,
    SSRFError,
    fetch_and_extract,
)
from soveryn.platform.web.search import (
    SearchError,
    search_via_searxng,
)


WEB_SEARCH_DEFAULT_K = 5
WEB_SEARCH_MAX_K = 20


# Per-agent user-agents. Vett identifies herself as the patrolling agent
# so external sources see which sovereign agent is fetching (and have a
# contact). Aetheria's lighter-weight fetches stay on the generic UA
# from soveryn.platform.web.fetch.
#
# Contact email is the org address. If/when dedicated bot mailboxes get
# stood up (e.g., vett@soverynintelligence.com or info@soverynintelligence.com),
# swap the value below — no schema change needed.
AGENT_USER_AGENTS: dict[str, str] = {
    "vett": (
        "SOVERYN-Vett/1.0 (Sovereign AI Research Agent; "
        "contact: jdeoliveira@soverynintelligence.com)"
    ),
}


def build_web_search_tool(
    *,
    searxng_url: str,
    owner_agent: str,
) -> ToolSpec:
    """Tool wrapping search_via_searxng with arg validation + structured errors."""

    def handler(args: Mapping[str, Any]) -> Any:
        query = args.get("query", "")
        if not isinstance(query, str) or not query.strip():
            raise ToolArgError("query must be a non-empty string")
        max_results = args.get("max_results", WEB_SEARCH_DEFAULT_K)
        if not isinstance(max_results, int) or isinstance(max_results, bool):
            raise ToolArgError("max_results must be an integer")
        if max_results <= 0 or max_results > WEB_SEARCH_MAX_K:
            raise ToolArgError(
                f"max_results must be between 1 and {WEB_SEARCH_MAX_K} (got {max_results})"
            )
        try:
            results = search_via_searxng(
                query, searxng_url=searxng_url, max_results=max_results,
            )
        except SearchError as e:
            return {"error": "search_failed", "message": str(e), "results": []}
        return {
            "query": query.strip(),
            "engine": "searxng",
            "results": [
                {
                    "title": r.title,
                    "url": r.url,
                    "snippet": r.snippet,
                    "source": r.engine,
                }
                for r in results
            ],
        }

    schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query.",
            },
            "max_results": {
                "type": "integer",
                "description": f"How many results to return (1-{WEB_SEARCH_MAX_K}).",
                "minimum": 1,
                "maximum": WEB_SEARCH_MAX_K,
                "default": WEB_SEARCH_DEFAULT_K,
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    }
    return ToolSpec(
        name="web_search",
        owner=owner_agent,
        schema=schema,
        handler=handler,
        description=(
            "Search the web via the local SearXNG instance. Returns title, "
            "url, and a short snippet per result. Use fetch_url to read a "
            "full page from a returned URL."
        ),
    )


def build_fetch_url_tool(*, owner_agent: str) -> ToolSpec:
    """Tool wrapping fetch_and_extract with arg validation + structured errors.

    Uses per-agent User-Agent when one is registered in AGENT_USER_AGENTS;
    otherwise falls back to the generic UA inside fetch_and_extract.
    """

    agent_ua = AGENT_USER_AGENTS.get(owner_agent)

    def handler(args: Mapping[str, Any]) -> Any:
        url = args.get("url", "")
        if not isinstance(url, str) or not url.strip():
            raise ToolArgError("url must be a non-empty string")
        max_chars = args.get("max_chars", DEFAULT_MAX_CHARS)
        if not isinstance(max_chars, int) or isinstance(max_chars, bool):
            raise ToolArgError("max_chars must be an integer")
        if max_chars <= 0 or max_chars > 32_000:
            raise ToolArgError(
                f"max_chars must be between 1 and 32000 (got {max_chars})"
            )
        try:
            page = fetch_and_extract(
                url, max_chars=max_chars, user_agent=agent_ua,
            )
        except SSRFError as e:
            return {"error": "ssrf_blocked", "message": str(e)}
        except FetchError as e:
            return {"error": "fetch_failed", "message": str(e)}
        return {
            "url": page.url,
            "title": page.title,
            "content": page.content,
            "truncated": page.truncated,
        }

    schema = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch. Must be http or https.",
            },
            "max_chars": {
                "type": "integer",
                "description": "Max characters of extracted content to return.",
                "minimum": 1,
                "maximum": 32_000,
                "default": DEFAULT_MAX_CHARS,
            },
        },
        "required": ["url"],
        "additionalProperties": False,
    }
    return ToolSpec(
        name="fetch_url",
        owner=owner_agent,
        schema=schema,
        handler=handler,
        description=(
            "Fetch a web page and extract its main readable content "
            "(title + article body), dropping nav and ads. Use after "
            "web_search to read a result in full."
        ),
    )


def register_web_tools(
    registry: ToolRegistry,
    *,
    searxng_url: str,
    owner_agent: str,
) -> None:
    """Register web_search + fetch_url for one agent."""
    registry.register(build_web_search_tool(
        searxng_url=searxng_url, owner_agent=owner_agent,
    ))
    registry.register(build_fetch_url_tool(owner_agent=owner_agent))
