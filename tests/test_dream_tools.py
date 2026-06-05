"""Tests for the Aetheria-only dream-recall tools."""

import sqlite3
import uuid
from datetime import datetime, timedelta

import pytest

from soveryn.agents.dream.tools import (
    build_recent_dreams_tool,
    build_search_dreams_tool,
    register_dream_tools,
)
from soveryn.platform.lattice.legacy import LAYER_DREAM, LatticeStore
from soveryn.platform.tools.registry import ToolRegistry


@pytest.fixture
def lattice_db(tmp_path):
    db = tmp_path / "lattice.db"
    LatticeStore(db)
    return db


def _insert_dream(db, *, content: str, ran_at_iso: str) -> str:
    node_id = str(uuid.uuid4())
    with sqlite3.connect(str(db)) as con:
        con.execute(
            "INSERT INTO nodes (id, type, layer, agent, content, "
            "intensity, salience, access_count, created_at, updated_at) "
            "VALUES (?, 'reflection', ?, 'aetheria', ?, 0.6, 0.6, 0, ?, ?)",
            (node_id, LAYER_DREAM, content, ran_at_iso, ran_at_iso),
        )
    return node_id


# ─── recent_dreams ──────────────────────────────────────────────────────────

def test_recent_dreams_returns_dreams_within_window(lattice_db):
    _insert_dream(
        lattice_db,
        content="last night's synthesis",
        ran_at_iso=(datetime.now() - timedelta(hours=8)).isoformat(),
    )
    _insert_dream(
        lattice_db,
        content="a week ago",
        ran_at_iso=(datetime.now() - timedelta(days=7)).isoformat(),
    )
    tool = build_recent_dreams_tool(
        lattice_db_path=lattice_db, owner_agent="aetheria",
    )
    result = tool.handler({"window_hours": 24})
    assert result["count"] == 1
    assert "last night" in result["dreams"][0]["content_head"]


def test_recent_dreams_defaults_to_24h(lattice_db):
    _insert_dream(
        lattice_db,
        content="recent",
        ran_at_iso=(datetime.now() - timedelta(hours=5)).isoformat(),
    )
    tool = build_recent_dreams_tool(
        lattice_db_path=lattice_db, owner_agent="aetheria",
    )
    result = tool.handler({})
    assert result["count"] == 1


def test_recent_dreams_returns_empty_when_no_dreams(lattice_db):
    tool = build_recent_dreams_tool(
        lattice_db_path=lattice_db, owner_agent="aetheria",
    )
    result = tool.handler({})
    assert result["count"] == 0
    assert result["dreams"] == []


# ─── search_dreams ──────────────────────────────────────────────────────────

def test_search_dreams_returns_layer_dream_only(lattice_db):
    """Should not return non-dream nodes even if their content matches."""
    _insert_dream(lattice_db, content="The funding round next month",
                   ran_at_iso=datetime.now().isoformat())
    # Insert a non-dream node with similar content
    with sqlite3.connect(str(lattice_db)) as con:
        con.execute(
            "INSERT INTO nodes (id, type, layer, agent, content, "
            "intensity, salience, access_count, created_at, updated_at) "
            "VALUES ('not-dream', 'memory', 'lattice', 'aetheria', "
            "'The funding round details', 0.5, 0.5, 0, ?, ?)",
            (datetime.now().isoformat(), datetime.now().isoformat()),
        )
    tool = build_search_dreams_tool(
        lattice_db_path=lattice_db, owner_agent="aetheria",
    )
    result = tool.handler({"query": "funding round"})
    # Should match the dream but NOT the non-dream
    ids = {m["reflection_node_id"] for m in result["matches"]}
    assert "not-dream" not in ids
    assert result["count"] >= 1


def test_search_dreams_empty_query_rejected(lattice_db):
    tool = build_search_dreams_tool(
        lattice_db_path=lattice_db, owner_agent="aetheria",
    )
    from soveryn.platform.tools.registry import ToolArgError
    with pytest.raises(ToolArgError):
        tool.handler({"query": ""})


# ─── register_dream_tools ──────────────────────────────────────────────────

def test_register_dream_tools_adds_for_aetheria_only(lattice_db):
    registry = ToolRegistry()
    register_dream_tools(
        registry,
        lattice_db_path=lattice_db,
        owner_agent="aetheria",
    )
    aetheria_tools = {s.name for s in registry.iter_tools_for_agent("aetheria")}
    assert "recent_dreams" in aetheria_tools
    assert "search_dreams" in aetheria_tools
    for other in ("vett", "scotty"):
        other_tools = {s.name for s in registry.iter_tools_for_agent(other)}
        assert "recent_dreams" not in other_tools
        assert "search_dreams" not in other_tools
