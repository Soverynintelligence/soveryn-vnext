"""Tests for CoordinationStore.promote_node — Phase A: cross-board promote.

Spec: docs/superpowers/specs/2026-06-01-coord-promote.md
"""

import json
import sqlite3
import pytest

from soveryn.platform.coordination import (
    CoordBoard,
    CoordinationError,
    CoordinationStore,
    CoordStatus,
)
from soveryn.platform.coordination.types import (
    COORDINATION_NODE_TYPE,
    LESSON_LEARNED_NODE_TYPE,
)
from soveryn.platform.lattice.legacy import LatticeStore


@pytest.fixture
def lattice_path(tmp_path):
    db_path = tmp_path / "test_lattice.db"
    LatticeStore(db_path)
    return db_path


@pytest.fixture
def store(lattice_path):
    return CoordinationStore(lattice_path)


# ─── Happy path ─────────────────────────────────────────────────────────────

def test_promote_signal_to_blueprint_archives_source_and_creates_target(store):
    signal = store.create_node(
        board=CoordBoard.SIGNAL, owner="vett",
        content="possible lead about EU sovereign AI funding",
    )
    source, target = store.promote_node(
        signal.id,
        target_board=CoordBoard.BLUEPRINT,
        new_content="Investigate EU sovereign AI funding pipeline for SOVERYN",
        acting_agent="aetheria",
    )
    assert source.id == signal.id
    assert source.status == CoordStatus.ARCHIVED
    assert source.archived_lesson_id is not None
    assert target.board == CoordBoard.BLUEPRINT
    assert target.status == CoordStatus.OPEN
    assert target.lattice_ref == signal.id
    assert target.owner == "aetheria"
    assert "Investigate EU sovereign AI funding" in target.content


def test_promote_to_friction_works_for_contradiction_path(store):
    """Promote also works Signal -> Friction when a lead turns out to be a contradiction."""
    signal = store.create_node(
        board=CoordBoard.SIGNAL, owner="vett",
        content="V.E.T.T. report claims X about grant program",
    )
    source, target = store.promote_node(
        signal.id,
        target_board=CoordBoard.FRICTION,
        new_content="X contradicts existing pinned memory — needs Aetheria arbitration",
        acting_agent="aetheria",
    )
    assert target.board == CoordBoard.FRICTION
    assert target.lattice_ref == signal.id


def test_promote_works_from_refining_state_too(store):
    """Promote shouldn't be Signal-only — a Refining node can be promoted too,
    since promote IS an archive + create. The state machine's archive rules
    apply (already-Archived rejected; everything else fine)."""
    n = store.create_node(board=CoordBoard.SIGNAL, owner="vett", content="lead")
    store.update_status(n.id, CoordStatus.REFINING, acting_agent="aetheria")
    source, target = store.promote_node(
        n.id,
        target_board=CoordBoard.BLUEPRINT,
        new_content="Refined plan",
        acting_agent="aetheria",
    )
    assert source.status == CoordStatus.ARCHIVED
    assert target.lattice_ref == n.id


# ─── Lattice ref linking ────────────────────────────────────────────────────

def test_promote_links_target_lattice_ref_to_source_id(store):
    signal = store.create_node(board=CoordBoard.SIGNAL, owner="vett", content="lead")
    _, target = store.promote_node(
        signal.id, target_board=CoordBoard.BLUEPRINT,
        new_content="plan", acting_agent="aetheria",
    )
    re_read = store.get_node(target.id)
    assert re_read.lattice_ref == signal.id


# ─── Lesson Learned ─────────────────────────────────────────────────────────

def test_promote_auto_lesson_when_none_provided(store, lattice_path):
    signal = store.create_node(board=CoordBoard.SIGNAL, owner="vett", content="lead")
    source, target = store.promote_node(
        signal.id, target_board=CoordBoard.BLUEPRINT,
        new_content="plan", acting_agent="aetheria",
    )
    con = sqlite3.connect(str(lattice_path))
    con.row_factory = sqlite3.Row
    lesson = con.execute(
        "SELECT content, provenance FROM nodes WHERE id = ?",
        (source.archived_lesson_id,),
    ).fetchone()
    con.close()
    assert lesson is not None
    # Auto-generated: "Promoted to Blueprint <id>"
    assert lesson["content"].startswith("Promoted to Blueprint ")
    assert target.id in lesson["content"]


def test_promote_custom_lesson_used_when_provided(store, lattice_path):
    signal = store.create_node(board=CoordBoard.SIGNAL, owner="vett", content="lead")
    custom = "We chose Blueprint because the lead matched our existing grant pipeline focus."
    source, target = store.promote_node(
        signal.id, target_board=CoordBoard.BLUEPRINT,
        new_content="plan", acting_agent="aetheria",
        lesson_learned_content=custom,
    )
    con = sqlite3.connect(str(lattice_path))
    lesson_content = con.execute(
        "SELECT content FROM nodes WHERE id = ?", (source.archived_lesson_id,),
    ).fetchone()[0]
    con.close()
    assert lesson_content == custom


def test_promote_lesson_carries_provenance_link_to_target(store, lattice_path):
    """The Lesson Learned should record which coord node it was promoted to,
    not just where it came from."""
    signal = store.create_node(board=CoordBoard.SIGNAL, owner="vett", content="lead")
    source, target = store.promote_node(
        signal.id, target_board=CoordBoard.BLUEPRINT,
        new_content="plan", acting_agent="aetheria",
    )
    con = sqlite3.connect(str(lattice_path))
    prov = json.loads(con.execute(
        "SELECT provenance FROM nodes WHERE id = ?", (source.archived_lesson_id,),
    ).fetchone()[0])
    con.close()
    assert prov["archived_coord_node_id"] == signal.id
    assert prov["promoted_to_coord_node_id"] == target.id
    assert prov["promoted_to_board"] == CoordBoard.BLUEPRINT.value
    assert prov["from_board"] == CoordBoard.SIGNAL.value
    assert prov["source"] == "coordination_promote"


# ─── Cross-reference instrumentation ────────────────────────────────────────

def test_promote_logs_cross_reference_source_to_target(store, lattice_path):
    signal = store.create_node(board=CoordBoard.SIGNAL, owner="vett", content="lead")
    _, target = store.promote_node(
        signal.id, target_board=CoordBoard.BLUEPRINT,
        new_content="plan", acting_agent="aetheria",
    )
    con = sqlite3.connect(str(lattice_path))
    refs = con.execute(
        "SELECT source_node_id, referenced_node_id, source_agent FROM coord_references "
        "WHERE source_node_id = ?",
        (signal.id,),
    ).fetchall()
    con.close()
    referenced = [r[1] for r in refs]
    # Source -> target promotion link is logged
    assert target.id in referenced
    # Source -> lesson link is logged
    assert any(r != target.id for r in referenced)
    # Acting agent is captured on every row
    assert all(r[2] == "aetheria" for r in refs)


# ─── Rejection cases ────────────────────────────────────────────────────────

def test_promote_already_archived_source_rejected(store):
    signal = store.create_node(board=CoordBoard.SIGNAL, owner="vett", content="lead")
    store.archive_node(signal.id, lesson_learned_content="dismissed", acting_agent="aetheria")
    with pytest.raises(CoordinationError, match="already Archived"):
        store.promote_node(
            signal.id, target_board=CoordBoard.BLUEPRINT,
            new_content="plan", acting_agent="aetheria",
        )


def test_promote_missing_source_rejected(store):
    with pytest.raises(CoordinationError, match="not found"):
        store.promote_node(
            "does-not-exist",
            target_board=CoordBoard.BLUEPRINT,
            new_content="plan", acting_agent="aetheria",
        )


def test_promote_to_signal_target_rejected_at_store_layer(store):
    """The tool layer also rejects this, but the store enforces it too as
    defense-in-depth — promoting INTO Signal makes no semantic sense."""
    signal = store.create_node(board=CoordBoard.SIGNAL, owner="vett", content="lead")
    with pytest.raises(CoordinationError, match="Signal"):
        store.promote_node(
            signal.id, target_board=CoordBoard.SIGNAL,
            new_content="x", acting_agent="aetheria",
        )


def test_promote_empty_new_content_rejected(store):
    signal = store.create_node(board=CoordBoard.SIGNAL, owner="vett", content="lead")
    with pytest.raises(CoordinationError, match="non-empty"):
        store.promote_node(
            signal.id, target_board=CoordBoard.BLUEPRINT,
            new_content="   ", acting_agent="aetheria",
        )


# ─── Atomicity ──────────────────────────────────────────────────────────────

def test_promote_keeps_source_visible_in_audit_after_archive(store):
    """Even though source is Archived (vanishes from board view), it stays
    queryable via include_archived for audit purposes."""
    signal = store.create_node(board=CoordBoard.SIGNAL, owner="vett", content="lead")
    source, target = store.promote_node(
        signal.id, target_board=CoordBoard.BLUEPRINT,
        new_content="plan", acting_agent="aetheria",
    )
    # Default board view: source absent, target present
    visible = store.list_nodes()
    visible_ids = {n.id for n in visible}
    assert source.id not in visible_ids
    assert target.id in visible_ids
    # Audit view: both present
    audit = store.list_nodes(include_archived=True)
    audit_ids = {n.id for n in audit}
    assert source.id in audit_ids
    assert target.id in audit_ids
