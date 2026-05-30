"""Aetheria-owned tool factories."""

from __future__ import annotations

from collections.abc import Callable

from soveryn.agents.aetheria.tools.lookup import build_get_node_tool
from soveryn.agents.aetheria.tools.recent import build_recent_tool
from soveryn.agents.aetheria.tools.search import (
    build_search_by_embedding_tool,
    build_search_by_keywords_tool,
)
from soveryn.platform.lattice.legacy import LatticeStore
from soveryn.platform.tools.registry import ToolRegistry


def register_aetheria_tools(
    registry: ToolRegistry,
    *,
    recall_lattice: LatticeStore,
    embed_fn: Callable[[str], tuple[float, ...]],
) -> None:
    """Register Aetheria's read-only lattice tools."""

    registry.register(
        build_search_by_embedding_tool(
            store=recall_lattice,
            embed_fn=embed_fn,
        )
    )
    registry.register(build_search_by_keywords_tool(store=recall_lattice))
    registry.register(build_get_node_tool(store=recall_lattice))
    registry.register(build_recent_tool(store=recall_lattice))
