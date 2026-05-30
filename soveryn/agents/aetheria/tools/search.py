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
