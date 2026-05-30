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
                "uncertain_count_by_class": {},
                "not_found": True,
            }
        return classify_and_render((node,))

    return ToolSpec(
        name="get_lattice_node",
        owner="aetheria",
        description="Look up one lattice node by id.",
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
