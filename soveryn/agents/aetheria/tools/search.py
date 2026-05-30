"""Aetheria lattice search tools."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from soveryn.agents.aetheria.tool_results import classify_and_render
from soveryn.platform.lattice.legacy import LatticeStore
from soveryn.platform.tools.registry import ToolSpec

DEFAULT_SEARCH_K = 5
DEFAULT_SEARCH_THRESHOLD = 0.70

EmbedFn = Callable[[str], tuple[float, ...]]


def build_search_by_embedding_tool(
    *,
    store: LatticeStore,
    embed_fn: EmbedFn,
) -> ToolSpec:
    """Build Aetheria's embedding-backed lattice search tool."""

    def handler(args: Mapping[str, Any]) -> dict[str, Any]:
        query = str(args["query"])
        k = int(args.get("k", DEFAULT_SEARCH_K))
        threshold = float(args.get("threshold", DEFAULT_SEARCH_THRESHOLD))
        embedding = tuple(float(value) for value in embed_fn(query))
        scored_nodes = store.find_nodes_by_embedding(
            "aetheria",
            embedding,
            limit=k,
            threshold=threshold,
        )
        nodes = tuple(node for node, _score in scored_nodes)
        return classify_and_render(nodes)

    return ToolSpec(
        name="search_lattice_by_embedding",
        owner="aetheria",
        description="Search Aetheria's lattice by embedding similarity.",
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


def build_search_by_keywords_tool(*, store: LatticeStore) -> ToolSpec:
    """Build Aetheria's keyword-backed lattice search tool."""

    def handler(args: Mapping[str, Any]) -> dict[str, Any]:
        keywords = tuple(str(item).strip() for item in args["keywords"] if str(item).strip())
        k = int(args.get("k", DEFAULT_SEARCH_K))

        nodes_by_id = {}
        for keyword in keywords:
            for node in store.find_nodes_by_keywords("aetheria", keyword, limit=k):
                nodes_by_id.setdefault(node.id, node)
                if len(nodes_by_id) >= k:
                    break
            if len(nodes_by_id) >= k:
                break

        return classify_and_render(tuple(nodes_by_id.values()))

    return ToolSpec(
        name="search_lattice_by_keywords",
        owner="aetheria",
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
