"""Aetheria lattice lookup tools."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from soveryn.agents.aetheria.tool_results import classify_and_render
from soveryn.platform.lattice.legacy import LatticeStore
from soveryn.platform.tools.registry import ToolSpec


def build_get_node_tool(*, store: LatticeStore) -> ToolSpec:
    """Build Aetheria's single-node lattice lookup tool."""

    def handler(args: Mapping[str, Any]) -> dict[str, Any]:
        node = store.get_node(str(args["node_id"]))
        if node is None:
            return {
                "stateable": [],
                "context_only": [],
                "uncertain_count_by_class": {},
                "context_only_returned": 0,
                "context_only_omitted": 0,
                "not_found": True,
            }
        # Detail mode: full body (Memory Grades PR1) — deep read without the
        # list-mode top-N / body caps that protect search/recent from firehose.
        return classify_and_render((node,), mode="detail")

    return ToolSpec(
        name="get_lattice_node",
        owner="aetheria",
        description=(
            "Look up one lattice node by id (full content, deep read). "
            "Use after search/recent when a truncated list hit needs the whole note."
        ),
        schema={
            "type": "object",
            "properties": {
                "node_id": {
                    "type": "string",
                    "description": "Lattice node id to retrieve.",
                },
            },
            "required": ["node_id"],
            "additionalProperties": False,
        },
        handler=handler,
    )
