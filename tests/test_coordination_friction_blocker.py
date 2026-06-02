"""Tests for Phase B: Friction-as-blocker.

Spec: docs/superpowers/specs/2026-06-01-coord-friction-blocker.md

Per Aetheria's spec, Friction nodes structurally block Blueprint nodes
from reaching Ready until the Friction is Archived. The block check fires
ONLY at the Refining -> Ready transition — Refining is still possible
under a Friction (work can continue; commitment pauses).
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
from soveryn.platform.lattice.legacy import LatticeStore


@pytest.fixture
def lattice_path(tmp_path):
    db_path = tmp_path / "test_lattice.db"
    LatticeStore(db_path)
    return db_path


@pytest.fixture
def store(lattice_path):
    return CoordinationStore(lattice_path)


def _new_blueprint(store, content="plan"):
    n = store.create_node(board=CoordBoard.BLUEPRINT, owner="scotty", content=content)
    store.update_status(n.id, CoordStatus.REFINING, acting_agent="aetheria")
    return n


def _new_friction(store, content="contradiction"):
    return store.create_node(board=CoordBoard.FRICTION, owner="aetheria", content=content)


# ─── add_block validation ───────────────────────────────────────────────────

def test_add_block_appends_to_provenance(store, lattice_path):
    f = _new_friction(store)
    bp = _new_blueprint(store)
    store.add_block(f.id, bp.id, acting_agent="aetheria")
    assert store.get_blocks(f.id) == (bp.id,)


def test_add_block_is_idempotent(store):
    f = _new_friction(store)
    bp = _new_blueprint(store)
    store.add_block(f.id, bp.id, acting_agent="aetheria")
    store.add_block(f.id, bp.id, acting_agent="aetheria")  # again — should no-op
    store.add_block(f.id, bp.id, acting_agent="aetheria")  # again — should no-op
    assert store.get_blocks(f.id) == (bp.id,)  # exactly one entry


def test_add_block_supports_multiple_blockers_for_same_blueprint(store):
    """Multiple Friction nodes can block the same Blueprint. Each one
    independently lists the Blueprint in its provenance.blocks."""
    f1 = _new_friction(store, content="contradiction 1")
    f2 = _new_friction(store, content="contradiction 2")
    bp = _new_blueprint(store)
    store.add_block(f1.id, bp.id, acting_agent="aetheria")
    store.add_block(f2.id, bp.id, acting_agent="vett")
    blockers = store.blueprint_blockers(bp.id)
    assert {b.id for b in blockers} == {f1.id, f2.id}


def test_add_block_supports_multiple_blueprints_blocked_by_same_friction(store):
    """One Friction can list multiple Blueprints in its blocks list."""
    f = _new_friction(store)
    bp1 = _new_blueprint(store, content="plan 1")
    bp2 = _new_blueprint(store, content="plan 2")
    store.add_block(f.id, bp1.id, acting_agent="aetheria")
    store.add_block(f.id, bp2.id, acting_agent="aetheria")
    assert set(store.get_blocks(f.id)) == {bp1.id, bp2.id}


# ─── add_block rejection cases ──────────────────────────────────────────────

def test_add_block_rejects_non_friction_source(store):
    """Only Friction nodes can be the source of a block."""
    not_friction = store.create_node(
        board=CoordBoard.SIGNAL, owner="vett", content="lead",
    )
    bp = _new_blueprint(store)
    with pytest.raises(CoordinationError, match="not Friction"):
        store.add_block(not_friction.id, bp.id, acting_agent="aetheria")


def test_add_block_rejects_non_blueprint_target(store):
    """Only Blueprint nodes can be blocked."""
    f = _new_friction(store)
    not_blueprint = store.create_node(
        board=CoordBoard.SIGNAL, owner="vett", content="lead",
    )
    with pytest.raises(CoordinationError, match="not Blueprint"):
        store.add_block(f.id, not_blueprint.id, acting_agent="aetheria")


def test_add_block_rejects_archived_friction_source(store):
    """Archived Frictions can't block — archive IS the unblock."""
    f = _new_friction(store)
    store.archive_node(f.id, lesson_learned_content="resolved", acting_agent="aetheria")
    bp = _new_blueprint(store)
    with pytest.raises(CoordinationError, match="Archived"):
        store.add_block(f.id, bp.id, acting_agent="aetheria")


def test_add_block_missing_friction_raises(store):
    bp = _new_blueprint(store)
    with pytest.raises(CoordinationError, match="not found"):
        store.add_block("does-not-exist", bp.id, acting_agent="aetheria")


def test_add_block_missing_blueprint_raises(store):
    f = _new_friction(store)
    with pytest.raises(CoordinationError, match="not found"):
        store.add_block(f.id, "does-not-exist", acting_agent="aetheria")


# ─── blueprint_blockers semantics ───────────────────────────────────────────

def test_blueprint_with_no_blockers_returns_empty(store):
    bp = _new_blueprint(store)
    assert store.blueprint_blockers(bp.id) == ()


def test_blueprint_blockers_excludes_archived_frictions(store):
    """Once a Friction is Archived, it stops blocking — even though its
    provenance.blocks list still mentions the Blueprint."""
    f = _new_friction(store)
    bp = _new_blueprint(store)
    store.add_block(f.id, bp.id, acting_agent="aetheria")
    assert len(store.blueprint_blockers(bp.id)) == 1
    store.archive_node(f.id, lesson_learned_content="resolved",
                        acting_agent="aetheria")
    assert store.blueprint_blockers(bp.id) == ()


# ─── State transition enforcement ───────────────────────────────────────────

def test_blueprint_ready_rejected_while_blocked(store):
    """The core invariant: Refining -> Ready refused while non-Archived
    Frictions block the Blueprint."""
    f = _new_friction(store)
    bp = _new_blueprint(store)
    store.add_block(f.id, bp.id, acting_agent="aetheria")
    with pytest.raises(CoordinationError, match="blocked by"):
        store.update_status(bp.id, CoordStatus.READY, acting_agent="aetheria")


def test_blueprint_ready_error_message_names_blockers(store):
    f = _new_friction(store)
    bp = _new_blueprint(store)
    store.add_block(f.id, bp.id, acting_agent="aetheria")
    with pytest.raises(CoordinationError) as exc_info:
        store.update_status(bp.id, CoordStatus.READY, acting_agent="aetheria")
    assert f.id in str(exc_info.value)


def test_blueprint_ready_accepted_after_friction_archived(store):
    """Archiving the Friction is the canonical unblock path."""
    f = _new_friction(store)
    bp = _new_blueprint(store)
    store.add_block(f.id, bp.id, acting_agent="aetheria")
    store.archive_node(f.id, lesson_learned_content="resolved",
                        acting_agent="aetheria")
    r = store.update_status(bp.id, CoordStatus.READY, acting_agent="aetheria")
    assert r.status == CoordStatus.READY


def test_blueprint_ready_rejected_until_ALL_frictions_archived(store):
    """If multiple Frictions block the same Blueprint, archiving just one
    is NOT enough — Ready stays blocked until they're all resolved."""
    f1 = _new_friction(store, content="block 1")
    f2 = _new_friction(store, content="block 2")
    bp = _new_blueprint(store)
    store.add_block(f1.id, bp.id, acting_agent="aetheria")
    store.add_block(f2.id, bp.id, acting_agent="aetheria")
    # Archive one
    store.archive_node(f1.id, lesson_learned_content="resolved 1",
                        acting_agent="aetheria")
    # Still blocked by f2
    with pytest.raises(CoordinationError, match="blocked by"):
        store.update_status(bp.id, CoordStatus.READY, acting_agent="aetheria")
    # Archive the second
    store.archive_node(f2.id, lesson_learned_content="resolved 2",
                        acting_agent="aetheria")
    # Now Ready works
    r = store.update_status(bp.id, CoordStatus.READY, acting_agent="aetheria")
    assert r.status == CoordStatus.READY


def test_blueprint_refining_still_works_under_block(store):
    """Open -> Refining is NOT blocked. Work continues; only commitment to
    Ready pauses. This is the intentional granularity per Aetheria's spec."""
    f = _new_friction(store)
    # Fresh open blueprint (don't auto-Refining via the helper)
    bp = store.create_node(board=CoordBoard.BLUEPRINT, owner="scotty", content="plan")
    store.add_block(f.id, bp.id, acting_agent="aetheria")
    # Open -> Refining still works
    r = store.update_status(bp.id, CoordStatus.REFINING, acting_agent="aetheria")
    assert r.status == CoordStatus.REFINING


def test_blueprint_archive_not_blocked(store):
    """Archive is also not blocked by Friction — explicit termination of a
    Blueprint shouldn't require resolving the Friction first."""
    f = _new_friction(store)
    bp = _new_blueprint(store)
    store.add_block(f.id, bp.id, acting_agent="aetheria")
    # Direct archive should work
    r = store.archive_node(bp.id, lesson_learned_content="cancelled",
                            acting_agent="aetheria")
    assert r.status == CoordStatus.ARCHIVED


# ─── Cross-reference instrumentation ────────────────────────────────────────

def test_add_block_logs_cross_reference(store, lattice_path):
    f = _new_friction(store)
    bp = _new_blueprint(store)
    store.add_block(f.id, bp.id, acting_agent="aetheria")
    con = sqlite3.connect(str(lattice_path))
    refs = con.execute(
        "SELECT source_node_id, referenced_node_id, source_agent "
        "FROM coord_references WHERE source_node_id = ?",
        (f.id,),
    ).fetchall()
    con.close()
    # The block declaration is logged
    referenced = [r[1] for r in refs]
    assert bp.id in referenced
    assert any(r[2] == "aetheria" for r in refs)
