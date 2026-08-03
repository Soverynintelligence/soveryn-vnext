"""Aetheria lattice search tools."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from soveryn.agents.aetheria.tool_results import classify_and_render
from soveryn.platform.lattice.legacy import LatticeStore
from soveryn.platform.lattice.miss_hint import build_miss_hint
from soveryn.platform.tools.registry import ToolSpec

DEFAULT_SEARCH_K = 5
DEFAULT_SEARCH_THRESHOLD = 0.70

EmbedFn = Callable[[str], tuple[float, ...]]


def build_search_by_embedding_tool(
    *,
    store: LatticeStore,
    embed_fn: EmbedFn,
    owner_agent: str = "aetheria",
) -> ToolSpec:
    """Build an embedding-backed lattice search tool for `owner_agent`.

    Parameterised 2026-08-02. Vett had only `search_library`, which filters to
    layer_filter="library" — 55 nodes of 2,709. Of her own 86 memories it could
    reach 19; of the 23 lattice nodes mentioning the honesty work it could reach
    one. Asked whether she remembered that work she truthfully answered no, and
    read as an agent with no history.

    The agent argument to find_nodes_by_embedding controls visibility: own nodes
    across every layer plus other agents' non-private nodes (fixed 2026-06-17).
    """

    def handler(args: Mapping[str, Any]) -> dict[str, Any]:
        query = str(args["query"])
        k = int(args.get("k", DEFAULT_SEARCH_K))
        threshold = float(args.get("threshold", DEFAULT_SEARCH_THRESHOLD))
        embedding = tuple(float(value) for value in embed_fn(query))
        scored_nodes = store.find_nodes_by_embedding(
            owner_agent,
            embedding,
            limit=k,
            threshold=threshold,
        )
        nodes = tuple(node for node, _score in scored_nodes)
        result = classify_and_render(nodes)
        # Miss Hint — when the search came up empty (no stateable, no
        # uncertain rows), probe the other layers with a coarse keyword
        # scan so the model knows where similar content lives instead
        # of just rephrasing into the same dry layer.
        if not result["stateable"] and not result["uncertain_count_by_class"]:
            result["miss_hint"] = build_miss_hint(store, owner_agent, query)
        return result

    return ToolSpec(
        name="search_lattice_by_embedding",
        owner=owner_agent,
        description=(
            "Search your own lattice memory by meaning, across every layer you "
            "can see — not just the shared library. Use this to recall past "
            "work, decisions and context."
        ),
        schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query to embed and compare against lattice nodes.",
                },
                "k": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": DEFAULT_SEARCH_K,
                },
                "threshold": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "default": DEFAULT_SEARCH_THRESHOLD,
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        handler=handler,
    )


def build_search_by_keywords_tool(*, store: LatticeStore,
                                 owner_agent: str = "aetheria") -> ToolSpec:
    """Build Aetheria's keyword-backed lattice search tool."""

    def handler(args: Mapping[str, Any]) -> dict[str, Any]:
        keywords = tuple(str(item).strip() for item in args["keywords"] if str(item).strip())
        k = int(args.get("k", DEFAULT_SEARCH_K))

        nodes_by_id = {}
        for keyword in keywords:
            for node in store.find_nodes_by_keywords(owner_agent, keyword, limit=k):
                nodes_by_id.setdefault(node.id, node)
                if len(nodes_by_id) >= k:
                    break
            if len(nodes_by_id) >= k:
                break

        result = classify_and_render(tuple(nodes_by_id.values()))
        # Miss Hint on empty — see embedding-tool handler for the why.
        if not result["stateable"] and not result["uncertain_count_by_class"]:
            joined_query = " ".join(keywords)
            result["miss_hint"] = build_miss_hint(store, owner_agent, joined_query)
        return result

    return ToolSpec(
        name="search_lattice_by_keywords",
        owner=owner_agent,
        description="Search Aetheria's lattice by content or tag keywords.",
        schema={
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "description": "Keywords to search for in lattice content and tags.",
                },
                "k": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": DEFAULT_SEARCH_K,
                },
            },
            "required": ["keywords"],
            "additionalProperties": False,
        },
        handler=handler,
    )
