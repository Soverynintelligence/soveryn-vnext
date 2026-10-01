"""Tests for soveryn.platform.salience.tools — promote_salience_candidate.

Task 5 of the Salience Engine plan: Aetheria's bridge from buffered
candidate to confirmed library entry (or dismissal). Tests stand a fake
LatticeStore so we can verify write_node args without spinning the real
lattice DB.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from soveryn.platform.salience.markers import MarkerHit
from soveryn.platform.salience.store import (
    create_buffer_table,
    insert_candidate,
)
from soveryn.platform.salience.tools import (
    build_promote_salience_candidate_tool,
    register_promote_salience_candidate_tool,
)
from soveryn.platform.tools.registry import ToolArgError, ToolRegistry


class FakeLatticeStore:
    def __init__(self) -> None:
        self.writes: list[dict] = []
        self._counter = 0

    def write_node(self, **kwargs):
        self._counter += 1
        node_id = f"node-{self._counter:04d}"
        record = dict(kwargs)
        record["_returned_id"] = node_id
        self.writes.append(record)
        return node_id


def _seed_turn(conv_db, *, session_id, rowid, role, content):
    conv_db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(conv_db)) as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                session_id TEXT, agent TEXT, role TEXT, content TEXT,
                timestamp TEXT, source TEXT, finish_reason TEXT
            );
        """)
        existing = con.execute(
            "SELECT COALESCE(MAX(rowid), 0) FROM conversations"
        ).fetchone()[0]
        for filler in range(existing + 1, rowid):
            con.execute(
                "INSERT INTO conversations VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session_id, "aetheria", "user", "_filler",
                 "2026-06-08T00:00:00", "direct", None),
            )
        con.execute(
            "INSERT INTO conversations VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, "aetheria", role, content,
             "2026-06-08T12:00:00", "direct", None),
        )


def _insert_pending(
    salience_db,
    *,
    session_id="sess-A",
    turn_rowid=5,
    turn_role="user",
    turn_content_head="The plan is locked. Ship it.",
    markers=None,
    heuristic_score=4.0,
    novelty_score=None,
):
    create_buffer_table(salience_db)
    if markers is None:
        markers = (MarkerHit(category="hard_lock", marker="locked", weight=4),)
    return insert_candidate(
        salience_db,
        session_id=session_id,
        turn_rowid=turn_rowid,
        turn_role=turn_role,
        turn_content_head=turn_content_head,
        markers=markers,
        heuristic_score=heuristic_score,
        novelty_score=novelty_score,
    )


def _buffer_status(salience_db, candidate_id):
    with sqlite3.connect(str(salience_db)) as con:
        row = con.execute(
            "SELECT status FROM salience_buffer WHERE id = ?", (candidate_id,)
        ).fetchone()
    return row[0] if row else None


@pytest.fixture
def paths(tmp_path):
    return tmp_path / "salience.db", tmp_path / "conv.db"


# ─── Promote: happy path ────────────────────────────────────────────────────

def test_promote_writes_library_node_with_provenance(paths):
    salience_db, conv_db = paths
    _seed_turn(conv_db, session_id="sess-A", rowid=5, role="user",
               content="The plan is locked. Ship it.")
    cand_id = _insert_pending(salience_db, turn_rowid=5)
    lattice = FakeLatticeStore()
    tool = build_promote_salience_candidate_tool(
        salience_db=salience_db, conv_db=conv_db,
        lattice_store=lattice, owner_agent="aetheria",
    )
    result = tool.handler({
        "candidate_id": cand_id,
        "library_intent": "Anchor: locked.",
    })
    assert result["status"] == "promoted"
    assert result["candidate_id"] == cand_id
    assert result["library_node_id"] == "node-0001"
    assert len(lattice.writes) == 1
    w = lattice.writes[0]
    assert w["agent"] == "aetheria"
    assert "Anchor: locked." in w["content"]
    assert "From: user turn — The plan is locked. Ship it." in w["content"]
    assert w["node_type"] == "library"
    assert w["layer"] == "library"
    assert w["intensity"] == 0.6
    assert "salience" in w["tags"]
    assert "promoted" in w["tags"]
    p = w["provenance"]
    assert p["source"] == "salience_promotion"
    assert p["cls"] == "told"  # user-turn promote is Channel A
    assert p["candidate_id"] == cand_id
    assert p["turn_rowid"] == 5
    assert p["session_id"] == "sess-A"
    assert p["turn_role"] == "user"
    assert p["library_intent"] == "Anchor: locked."
    # Buffer row flipped out of pending
    assert _buffer_status(salience_db, cand_id) == "promoted"


def test_promote_without_intent_omits_intent_prefix(paths):
    salience_db, conv_db = paths
    _seed_turn(conv_db, session_id="sess-A", rowid=5, role="user",
               content="The plan is locked. Ship it.")
    cand_id = _insert_pending(salience_db, turn_rowid=5)
    lattice = FakeLatticeStore()
    tool = build_promote_salience_candidate_tool(
        salience_db=salience_db, conv_db=conv_db,
        lattice_store=lattice, owner_agent="aetheria",
    )
    result = tool.handler({"candidate_id": cand_id})
    assert result["status"] == "promoted"
    w = lattice.writes[0]
    assert w["content"].startswith("From: user turn — ")
    assert "\n\nFrom:" not in w["content"]
    assert w["provenance"]["library_intent"] is None


def test_promote_falls_back_to_turn_head_when_conv_db_missing_row(paths):
    salience_db, conv_db = paths
    # No turn seeded — conv_db has no row at turn_rowid=5
    cand_id = _insert_pending(
        salience_db, turn_rowid=5,
        turn_content_head="Head fallback content.",
    )
    lattice = FakeLatticeStore()
    tool = build_promote_salience_candidate_tool(
        salience_db=salience_db, conv_db=conv_db,
        lattice_store=lattice, owner_agent="aetheria",
    )
    result = tool.handler({"candidate_id": cand_id})
    assert result["status"] == "promoted"
    assert len(lattice.writes) == 1
    assert "Head fallback content." in lattice.writes[0]["content"]


def test_promote_passes_markers_into_provenance(paths):
    salience_db, conv_db = paths
    _seed_turn(conv_db, session_id="sess-A", rowid=5, role="assistant",
               content="something witnessed.")
    markers = (
        MarkerHit(category="hard_lock", marker="locked", weight=4),
        MarkerHit(category="pivot", marker="actually", weight=2),
    )
    cand_id = _insert_pending(
        salience_db, turn_rowid=5, turn_role="assistant", markers=markers,
        heuristic_score=6.0,
    )
    lattice = FakeLatticeStore()
    tool = build_promote_salience_candidate_tool(
        salience_db=salience_db, conv_db=conv_db,
        lattice_store=lattice, owner_agent="aetheria",
    )
    tool.handler({"candidate_id": cand_id})
    prov_markers = lattice.writes[0]["provenance"]["markers"]
    assert isinstance(prov_markers, list)
    assert len(prov_markers) == 2
    cats = {m["category"] for m in prov_markers}
    assert cats == {"hard_lock", "pivot"}


# ─── Errors ─────────────────────────────────────────────────────────────────

def test_promote_unknown_candidate_id_errors(paths):
    salience_db, conv_db = paths
    create_buffer_table(salience_db)
    lattice = FakeLatticeStore()
    tool = build_promote_salience_candidate_tool(
        salience_db=salience_db, conv_db=conv_db,
        lattice_store=lattice, owner_agent="aetheria",
    )
    with pytest.raises(ToolArgError, match="not found"):
        tool.handler({"candidate_id": "no-such-id"})
    assert lattice.writes == []


def test_promote_already_promoted_errors(paths):
    salience_db, conv_db = paths
    _seed_turn(conv_db, session_id="sess-A", rowid=5, role="user",
               content="x")
    cand_id = _insert_pending(salience_db, turn_rowid=5)
    lattice = FakeLatticeStore()
    tool = build_promote_salience_candidate_tool(
        salience_db=salience_db, conv_db=conv_db,
        lattice_store=lattice, owner_agent="aetheria",
    )
    tool.handler({"candidate_id": cand_id})
    with pytest.raises(ToolArgError, match="already"):
        tool.handler({"candidate_id": cand_id})


def test_promote_rejects_empty_candidate_id(paths):
    salience_db, conv_db = paths
    create_buffer_table(salience_db)
    lattice = FakeLatticeStore()
    tool = build_promote_salience_candidate_tool(
        salience_db=salience_db, conv_db=conv_db,
        lattice_store=lattice, owner_agent="aetheria",
    )
    with pytest.raises(ToolArgError, match="candidate_id"):
        tool.handler({})
    with pytest.raises(ToolArgError, match="candidate_id"):
        tool.handler({"candidate_id": ""})
    with pytest.raises(ToolArgError, match="candidate_id"):
        tool.handler({"candidate_id": "   "})


def test_promote_rejects_invalid_action(paths):
    salience_db, conv_db = paths
    cand_id = _insert_pending(salience_db)
    lattice = FakeLatticeStore()
    tool = build_promote_salience_candidate_tool(
        salience_db=salience_db, conv_db=conv_db,
        lattice_store=lattice, owner_agent="aetheria",
    )
    with pytest.raises(ToolArgError, match="action"):
        tool.handler({"candidate_id": cand_id, "action": "archive"})


def test_promote_rejects_non_string_intent(paths):
    salience_db, conv_db = paths
    cand_id = _insert_pending(salience_db)
    lattice = FakeLatticeStore()
    tool = build_promote_salience_candidate_tool(
        salience_db=salience_db, conv_db=conv_db,
        lattice_store=lattice, owner_agent="aetheria",
    )
    with pytest.raises(ToolArgError, match="library_intent"):
        tool.handler({"candidate_id": cand_id, "library_intent": 42})


# ─── Dismiss ────────────────────────────────────────────────────────────────

def test_promote_dismiss_action(paths):
    salience_db, conv_db = paths
    cand_id = _insert_pending(salience_db)
    lattice = FakeLatticeStore()
    tool = build_promote_salience_candidate_tool(
        salience_db=salience_db, conv_db=conv_db,
        lattice_store=lattice, owner_agent="aetheria",
    )
    result = tool.handler({"candidate_id": cand_id, "action": "dismiss"})
    assert result == {"status": "dismissed", "candidate_id": cand_id}
    assert lattice.writes == []
    assert _buffer_status(salience_db, cand_id) == "dismissed"


def test_promote_dismiss_then_redismiss_errors(paths):
    salience_db, conv_db = paths
    cand_id = _insert_pending(salience_db)
    lattice = FakeLatticeStore()
    tool = build_promote_salience_candidate_tool(
        salience_db=salience_db, conv_db=conv_db,
        lattice_store=lattice, owner_agent="aetheria",
    )
    tool.handler({"candidate_id": cand_id, "action": "dismiss"})
    with pytest.raises(ToolArgError, match="already dismissed"):
        tool.handler({"candidate_id": cand_id, "action": "dismiss"})


def test_promote_dismiss_then_promote_errors(paths):
    salience_db, conv_db = paths
    cand_id = _insert_pending(salience_db)
    lattice = FakeLatticeStore()
    tool = build_promote_salience_candidate_tool(
        salience_db=salience_db, conv_db=conv_db,
        lattice_store=lattice, owner_agent="aetheria",
    )
    tool.handler({"candidate_id": cand_id, "action": "dismiss"})
    with pytest.raises(ToolArgError, match="already dismissed"):
        tool.handler({"candidate_id": cand_id, "action": "promote"})
    assert lattice.writes == []


# ─── Registration ──────────────────────────────────────────────────────────

def test_register_helper_registers_tool(paths):
    salience_db, conv_db = paths
    create_buffer_table(salience_db)
    lattice = FakeLatticeStore()
    registry = ToolRegistry()
    register_promote_salience_candidate_tool(
        registry,
        salience_db=salience_db,
        conv_db=conv_db,
        lattice_store=lattice,
    )
    specs = registry.iter_tools_for_agent("aetheria")
    names = {s.name: s for s in specs}
    assert "promote_salience_candidate" in names
    assert names["promote_salience_candidate"].owner == "aetheria"
    # Not registered for the other agents.
    for other in ("vett", "scotty"):
        other_names = {s.name for s in registry.iter_tools_for_agent(other)}
        assert "promote_salience_candidate" not in other_names
