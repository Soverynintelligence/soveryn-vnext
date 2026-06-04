"""Tests for the recent_self_audit tool.

Verifies:
- Coord event log entries surface (create/promote/archive)
- Coord read references surface and group correctly per timestamp
- Library writes surface from the nodes table
- Owner-key filtering — agents see only their own actions
- Window filtering — outside-window actions excluded
- audit_coverage_note is always included
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from soveryn.platform.audit.tools import (
    AUDIT_COVERAGE_NOTE,
    MAX_RECORDS,
    MAX_WINDOW_MINUTES,
    build_recent_self_audit_tool,
)
from soveryn.platform.coordination import (
    CoordBoard,
    CoordinationStore,
    CoordStatus,
)
from soveryn.platform.lattice.legacy import LAYER_LIBRARY, LatticeStore
from soveryn.platform.tools.registry import ToolArgError


@pytest.fixture
def lattice_db(tmp_path):
    db = tmp_path / "test_lattice.db"
    LatticeStore(db)
    return db


@pytest.fixture
def coord_store(lattice_db):
    """Real CoordinationStore so the event log fills naturally via mutations."""
    return CoordinationStore(lattice_db)


# ─── Argument validation ────────────────────────────────────────────────────

def test_recent_self_audit_rejects_non_positive_window(lattice_db):
    tool = build_recent_self_audit_tool(
        lattice_db_path=lattice_db, owner_agent="aetheria",
    )
    with pytest.raises(ToolArgError, match="positive integer"):
        tool.handler({"window_minutes": 0})
    with pytest.raises(ToolArgError, match="positive integer"):
        tool.handler({"window_minutes": -10})


def test_recent_self_audit_rejects_excessive_window(lattice_db):
    tool = build_recent_self_audit_tool(
        lattice_db_path=lattice_db, owner_agent="aetheria",
    )
    with pytest.raises(ToolArgError, match="<= "):
        tool.handler({"window_minutes": MAX_WINDOW_MINUTES + 1})


# ─── Empty case ─────────────────────────────────────────────────────────────

def test_recent_self_audit_returns_empty_actions_when_no_history(lattice_db):
    tool = build_recent_self_audit_tool(
        lattice_db_path=lattice_db, owner_agent="aetheria",
    )
    result = tool.handler({})
    assert result["count"] == 0
    assert result["actions"] == []
    # Coverage note ALWAYS present, even on empty results
    assert result["audit_coverage_note"] == AUDIT_COVERAGE_NOTE


# ─── Coord event log surfacing ──────────────────────────────────────────────

def test_recent_self_audit_surfaces_create_event(lattice_db, coord_store):
    # Use an in-memory event bus so emit() happens
    from soveryn.platform.coordination.events import InMemoryEventBus
    store = CoordinationStore(lattice_db, event_bus=InMemoryEventBus())
    store.create_node(
        board=CoordBoard.SIGNAL, owner="aetheria", content="probe signal",
    )
    tool = build_recent_self_audit_tool(
        lattice_db_path=lattice_db, owner_agent="aetheria",
    )
    result = tool.handler({})
    assert result["count"] == 1
    a = result["actions"][0]
    assert a["kind"] == "coord.node_created"
    assert a["details"]["board"] == "Signal"


def test_recent_self_audit_surfaces_promote_with_chain_metadata(
    lattice_db, coord_store,
):
    from soveryn.platform.coordination.events import InMemoryEventBus
    store = CoordinationStore(lattice_db, event_bus=InMemoryEventBus())
    sig = store.create_node(
        board=CoordBoard.SIGNAL, owner="vett", content="lead",
    )
    store.promote_node(
        sig.id, target_board=CoordBoard.BLUEPRINT,
        new_content="plan", acting_agent="aetheria",
    )
    tool = build_recent_self_audit_tool(
        lattice_db_path=lattice_db, owner_agent="aetheria",
    )
    result = tool.handler({})
    promote_records = [a for a in result["actions"] if a["kind"] == "coord.promoted"]
    assert len(promote_records) == 1
    p = promote_records[0]
    assert p["details"]["target_board"] == "Blueprint"
    assert p["details"]["source_node_id"] == sig.id


# ─── Coord read references ──────────────────────────────────────────────────

def test_recent_self_audit_surfaces_read_calls(lattice_db, coord_store):
    # Seed two nodes, then read them via a reading_agent so coord_references fires
    coord_store.create_node(
        board=CoordBoard.SIGNAL, owner="vett", content="A",
    )
    coord_store.create_node(
        board=CoordBoard.SIGNAL, owner="vett", content="B",
    )
    coord_store.list_nodes(reading_agent="aetheria")
    tool = build_recent_self_audit_tool(
        lattice_db_path=lattice_db, owner_agent="aetheria",
    )
    result = tool.handler({})
    reads = [a for a in result["actions"] if a["kind"] == "coord.read"]
    assert len(reads) == 1
    # Two nodes were read in that one list_nodes call → ref_count == 2
    assert reads[0]["details"]["ref_count"] == 2


# ─── Library writes ─────────────────────────────────────────────────────────

def test_recent_self_audit_surfaces_library_writes(lattice_db):
    store = LatticeStore(lattice_db)
    store.write_node(
        agent="aetheria",
        content="verified fact about EU funding",
        node_type="library",
        layer=LAYER_LIBRARY,
        intensity=0.6,
        tags=("funding", "eu"),
    )
    tool = build_recent_self_audit_tool(
        lattice_db_path=lattice_db, owner_agent="aetheria",
    )
    result = tool.handler({})
    library_records = [a for a in result["actions"] if a["kind"] == "library.write"]
    assert len(library_records) == 1
    assert library_records[0]["details"]["tags"] == ["funding", "eu"]
    assert "EU funding" in library_records[0]["details"]["content_head"]


# ─── Owner-key isolation ────────────────────────────────────────────────────

def test_recent_self_audit_filters_to_owner_only(lattice_db):
    """Aetheria's audit shouldn't show Vett's actions and vice versa."""
    from soveryn.platform.coordination.events import InMemoryEventBus
    store = CoordinationStore(lattice_db, event_bus=InMemoryEventBus())
    store.create_node(
        board=CoordBoard.SIGNAL, owner="vett", content="vett signal",
    )
    store.create_node(
        board=CoordBoard.SIGNAL, owner="aetheria", content="aetheria signal",
    )
    aetheria_tool = build_recent_self_audit_tool(
        lattice_db_path=lattice_db, owner_agent="aetheria",
    )
    vett_tool = build_recent_self_audit_tool(
        lattice_db_path=lattice_db, owner_agent="vett",
    )
    aetheria_result = aetheria_tool.handler({})
    vett_result = vett_tool.handler({})
    assert aetheria_result["count"] == 1
    assert vett_result["count"] == 1
    assert "aetheria signal" not in vett_result["actions"][0]["details"].get("content_head", "")
    assert "vett signal" not in aetheria_result["actions"][0]["details"].get("content_head", "")


# ─── Window filtering ───────────────────────────────────────────────────────

def test_recent_self_audit_excludes_actions_outside_window(lattice_db):
    """An old coord event row outside the window must not appear."""
    # Manually insert an old event row directly into coord_event_log
    old_ts = (datetime.now() - timedelta(hours=2)).isoformat()
    with sqlite3.connect(str(lattice_db)) as con:
        con.execute(
            "INSERT INTO coord_event_log "
            "(id, kind, node_id, actor_agent, chain_depth, payload_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), "node_created", str(uuid.uuid4()),
             "aetheria", 0, "{}", old_ts),
        )
    tool = build_recent_self_audit_tool(
        lattice_db_path=lattice_db, owner_agent="aetheria",
    )
    # 60-min window (default) — old row should be excluded
    result = tool.handler({})
    assert result["count"] == 0
    # 180-min window — old row should be included
    result = tool.handler({"window_minutes": 180})
    assert result["count"] == 1


# ─── Coverage note + chronological order ────────────────────────────────────

def test_recent_self_audit_returns_actions_most_recent_first(lattice_db):
    """When multiple actions land, the timeline should be sorted DESC by timestamp."""
    from soveryn.platform.coordination.events import InMemoryEventBus
    store = CoordinationStore(lattice_db, event_bus=InMemoryEventBus())
    store.create_node(
        board=CoordBoard.SIGNAL, owner="aetheria", content="first",
    )
    store.create_node(
        board=CoordBoard.BLUEPRINT, owner="aetheria", content="second",
    )
    tool = build_recent_self_audit_tool(
        lattice_db_path=lattice_db, owner_agent="aetheria",
    )
    result = tool.handler({})
    timestamps = [a["timestamp"] for a in result["actions"]]
    # Most recent FIRST
    assert timestamps == sorted(timestamps, reverse=True)


def test_recent_self_audit_always_includes_coverage_note(lattice_db):
    """The coverage note is critical for the agent's epistemic discipline —
    it must always be present so the agent doesn't assume absence of audit
    means absence of action."""
    tool = build_recent_self_audit_tool(
        lattice_db_path=lattice_db, owner_agent="aetheria",
    )
    # Empty case
    assert tool.handler({})["audit_coverage_note"] == AUDIT_COVERAGE_NOTE
    # With data
    store = LatticeStore(lattice_db)
    store.write_node(
        agent="aetheria", content="fact", node_type="library",
        layer=LAYER_LIBRARY, intensity=0.6,
    )
    assert tool.handler({})["audit_coverage_note"] == AUDIT_COVERAGE_NOTE
