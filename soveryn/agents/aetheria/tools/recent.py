"""Aetheria recent lattice entry tool."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from soveryn.agents.aetheria.tool_results import classify_and_render
from soveryn.platform.lattice.legacy import LatticeStore
from soveryn.platform.tools.registry import ToolSpec

DEFAULT_RECENT_LIMIT = 10


def build_recent_tool(*, store: LatticeStore) -> ToolSpec:
    """Build Aetheria's chronological recent-lattice view."""

    def handler(args: Mapping[str, Any]) -> dict[str, Any]:
        limit = int(args.get("limit", DEFAULT_RECENT_LIMIT))
        nodes = store.iter_nodes(agent="aetheria")
        sorted_nodes = sorted(nodes, key=lambda node: node.created_at, reverse=True)
        return classify_and_render(tuple(sorted_nodes[:limit]))

    return ToolSpec(
        name="recent_lattice_entries",
        owner="aetheria",
        description="Return Aetheria's most recent lattice entries.",
        schema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": DEFAULT_RECENT_LIMIT,
                },
            },
            "additionalProperties": False,
        },
        handler=handler,
    )
