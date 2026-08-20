"""Aetheria recent lattice entry tool."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from soveryn.agents.aetheria.tool_results import classify_and_render
from soveryn.platform.lattice.legacy import LatticeStore
from soveryn.platform.tools.registry import ToolSpec

DEFAULT_RECENT_LIMIT = 10


def build_recent_tool(
    *,
    store: LatticeStore,
    owner_agent: str = "aetheria",
) -> ToolSpec:
    """Build a chronological recent-lattice view scoped to `owner_agent`.

    Parameterised 2026-08-20 alongside get_lattice_node. The agent name is
    threaded all the way into `iter_nodes`, not just onto `ToolSpec.owner`:
    this handler filtered on the literal string "aetheria", so registering it
    for another agent without this change would have served Kernel her private
    memories and presented them as his own.

    `iter_nodes(agent=...)` is a strict owner match — unlike search, which also
    surfaces other agents' non-private nodes. "Recent" means *mine*.
    """

    def handler(args: Mapping[str, Any]) -> dict[str, Any]:
        limit = int(args.get("limit", DEFAULT_RECENT_LIMIT))
        nodes = store.iter_nodes(agent=owner_agent)
        sorted_nodes = sorted(nodes, key=lambda node: node.created_at, reverse=True)
        return classify_and_render(tuple(sorted_nodes[:limit]))

    return ToolSpec(
        name="recent_lattice_entries",
        owner=owner_agent,
        description="Return your most recent lattice entries.",
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
