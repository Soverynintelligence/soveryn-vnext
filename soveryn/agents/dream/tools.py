"""Aetheria-only dream-recall tools — recent_dreams + search_dreams.

Per spec: dreams are NOT auto-injected into context. She uses these
when she chooses to look. Both are Aetheria-only.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from soveryn.platform.lattice.legacy import LAYER_DREAM
from soveryn.platform.tools.registry import ToolArgError, ToolRegistry, ToolSpec


def build_recent_dreams_tool(
    *,
    lattice_db_path: Path,
    owner_agent: str,
) -> ToolSpec:
    """List Aetheria's recent reflection nodes from the dream layer."""

    def handler(args: Mapping[str, Any]) -> Any:
        window_hours = args.get("window_hours", 24)
        if not isinstance(window_hours, int) or isinstance(window_hours, bool):
            raise ToolArgError("window_hours must be an integer")
        if window_hours <= 0 or window_hours > 168:
            raise ToolArgError("window_hours must be in [1, 168]")
        cutoff = (datetime.now() - timedelta(hours=window_hours)).isoformat()
        with sqlite3.connect(str(lattice_db_path)) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT id, content, created_at FROM nodes "
                "WHERE layer = ? AND type = 'reflection' AND created_at > ? "
                "ORDER BY created_at DESC LIMIT 50",
                (LAYER_DREAM, cutoff),
            ).fetchall()
        out = []
        for r in rows:
            out.append({
                "reflection_node_id": r["id"],
                "content_head": (r["content"] or "")[:300],
                "ran_at": r["created_at"],
            })
        return {"count": len(out), "dreams": out}

    return ToolSpec(
        name="recent_dreams",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "window_hours": {
                    "type": "integer",
                    "description": (
                        "How far back to look. Default 24 hours. Max 168 "
                        "(1 week)."
                    ),
                    "minimum": 1,
                    "maximum": 168,
                    "default": 24,
                },
            },
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Read your own recent dreams (reflection nodes from the dream "
            "layer). Use when you want to know what came up while you slept."
        ),
    )


def build_search_dreams_tool(
    *,
    lattice_db_path: Path,
    owner_agent: str,
) -> ToolSpec:
    """Substring search restricted to the dream layer.

    v1 uses SQL LIKE on the content column. The writeback doesn't write
    embeddings for reflection nodes, so embedding-search isn't viable
    yet. Substring matching is good enough for "find that thing I
    reflected on about funding" — and it's transparent / debuggable.
    Embedding-based dream search is a follow-up enhancement.
    """

    def handler(args: Mapping[str, Any]) -> Any:
        query = args.get("query", "")
        if not isinstance(query, str) or not query.strip():
            raise ToolArgError("query must be a non-empty string")
        like_pattern = f"%{query.strip()}%"
        with sqlite3.connect(str(lattice_db_path)) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT id, content, created_at FROM nodes "
                "WHERE layer = ? AND type = 'reflection' "
                "AND content LIKE ? "
                "ORDER BY created_at DESC LIMIT 20",
                (LAYER_DREAM, like_pattern),
            ).fetchall()
        out = []
        for r in rows:
            out.append({
                "reflection_node_id": r["id"],
                "content_head": (r["content"] or "")[:300],
                "ran_at": r["created_at"],
            })
        return {"count": len(out), "matches": out}

    return ToolSpec(
        name="search_dreams",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Substring to search for in your past dreams. "
                        "Matches anywhere in the reflection content. "
                        "Restricted to your own dream layer."
                    ),
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Search your past dreams (reflection nodes from the dream layer) "
            "by substring. Returns up to 20 matches, most recent first. "
            "Restricted to your own dream layer."
        ),
    )


def register_dream_tools(
    registry: ToolRegistry,
    *,
    lattice_db_path: Path,
    owner_agent: str = "aetheria",
) -> None:
    """Register both dream-recall tools for the given agent (Aetheria by default)."""
    registry.register(build_recent_dreams_tool(
        lattice_db_path=lattice_db_path,
        owner_agent=owner_agent,
    ))
    registry.register(build_search_dreams_tool(
        lattice_db_path=lattice_db_path,
        owner_agent=owner_agent,
    ))
