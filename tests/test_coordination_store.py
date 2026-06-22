"""Tests for soveryn.platform.coordination.store.CoordinationStore.

Coordination Boards spec (Aetheria 2026-06-01, locked):
- 3 boards: Signal / Blueprint / Friction
- 4-state lifecycle: Open -> Refining -> Ready -> Archived
- Archive != Delete; archive writes a Lesson Learned lattice node
- No backward transitions; Archived is terminal
- Cross-references logged for Phase-2 weight back-computation

Tests use the live nodes schema (we extend it, not duplicate), so each test
gets a fresh tmp_path-backed LatticeStore.
"""

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
    """A fresh lattice DB with the full schema initialized."""
    db_path = tmp_path / "test_lattice.db"
    LatticeStore(db_path)  # init schema (idempotent)
    return db_path


@pytest.fixture
def store(lattice_path):
    return CoordinationStore(lattice_path)


# ─── Schema migration ───────────────────────────────────────────────────────

def test_schema_includes_coord_references_table(lattice_path):
    """The coord_references table must be created by LatticeStore init."""
    con = sqlite3.connect(str(lattice_path))
    tables = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    con.close()
    assert "coord_references" in tables


def test_coord_references_indexes_present(lattice_path):
    """The three indexes on coord_references must exist for query performance."""
    con = sqlite3.connect(str(lattice_path))
    idxs = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='coord_references'"
    ).fetchall()}
    con.close()
    assert "idx_coord_refs_source" in idxs
    assert "idx_coord_refs_referenced" in idxs
    assert "idx_coord_refs_agent" in idxs


# ─── Create + Read ──────────────────────────────────────────────────────────

def test_create_node_returns_node_with_open_status(store):
    node = store.create_node(
        board=CoordBoard.SIGNAL, owner="vett", content="possible lead",
    )
    assert node.board == CoordBoard.SIGNAL
    assert node.status == CoordStatus.OPEN
    assert node.owner == "vett"
    assert node.content == "possible lead"
    assert node.lattice_ref is None
    assert node.archived_lesson_id is None
    assert len(node.id) == 36  # UUID


def test_create_node_rejects_empty_content(store):
    with pytest.raises(CoordinationError, match="non-empty"):
        store.create_node(board=CoordBoard.SIGNAL, owner="vett", content="")
    with pytest.raises(CoordinationError, match="non-empty"):
        store.create_node(board=CoordBoard.SIGNAL, owner="vett", content="   ")


def test_create_node_preserves_lattice_ref(store):
    ref = "some-existing-lattice-node-uuid"
    node = store.create_node(
        board=CoordBoard.BLUEPRINT, owner="scotty",
        content="execution plan for X", lattice_ref=ref,
    )
    assert node.lattice_ref == ref


def test_create_node_persisted_in_nodes_table_with_coordination_type(store, lattice_path):
    node = store.create_node(
        board=CoordBoard.SIGNAL, owner="vett", content="lead",
    )
    con = sqlite3.connect(str(lattice_path))
    row = con.execute(
        "SELECT type, agent, content FROM nodes WHERE id = ?", (node.id,)
    ).fetchone()
    con.close()
    assert row is not None
    assert row[0] == COORDINATION_NODE_TYPE
    assert row[1] == "vett"
    assert row[2] == "lead"


def test_list_nodes_returns_only_coordination_typed(store):
    store.create_node(board=CoordBoard.SIGNAL, owner="vett", content="A")
    store.create_node(board=CoordBoard.BLUEPRINT, owner="scotty", content="B")
    listed = store.list_nodes()
    assert len(listed) == 2
    assert {n.content for n in listed} == {"A", "B"}


def test_list_nodes_filters_by_board(store):
    store.create_node(board=CoordBoard.SIGNAL, owner="vett", content="A")
    store.create_node(board=CoordBoard.BLUEPRINT, owner="scotty", content="B")
    store.create_node(board=CoordBoard.FRICTION, owner="aetheria", content="C")
    sig = store.list_nodes(board=CoordBoard.SIGNAL)
    assert [n.content for n in sig] == ["A"]
    bp = store.list_nodes(board=CoordBoard.BLUEPRINT)
    assert [n.content for n in bp] == ["B"]


def test_list_nodes_filters_by_status(store):
    a = store.create_node(board=CoordBoard.SIGNAL, owner="vett", content="A")
    b = store.create_node(board=CoordBoard.SIGNAL, owner="vett", content="B")
    store.update_status(a.id, CoordStatus.REFINING, acting_agent="aetheria")
    refining = store.list_nodes(status=CoordStatus.REFINING)
    assert [n.content for n in refining] == ["A"]
    open_only = store.list_nodes(status=CoordStatus.OPEN)
    assert [n.content for n in open_only] == ["B"]


def test_list_nodes_excludes_archived_by_default(store):
    a = store.create_node(board=CoordBoard.SIGNAL, owner="vett", content="A")
    store.update_status(a.id, CoordStatus.REFINING, acting_agent="aetheria")
    store.update_status(a.id, CoordStatus.READY, acting_agent="aetheria")
    store.archive_node(a.id, lesson_learned_content="learned A", acting_agent="aetheria")
    # Default list excludes Archived (board view)
    assert store.list_nodes() == ()
    # Audit list includes them
    audit = store.list_nodes(include_archived=True)
    assert len(audit) == 1
    assert audit[0].status == CoordStatus.ARCHIVED


def test_get_node_returns_none_for_missing_id(store):
    assert store.get_node("does-not-exist") is None


def test_get_node_returns_node_for_existing(store):
    created = store.create_node(board=CoordBoard.SIGNAL, owner="vett", content="A")
    got = store.get_node(created.id)
    assert got is not None
    assert got.id == created.id
    assert got.content == "A"


# ─── State machine ──────────────────────────────────────────────────────────

def test_state_transition_open_to_refining(store):
    node = store.create_node(board=CoordBoard.SIGNAL, owner="vett", content="A")
    r = store.update_status(node.id, CoordStatus.REFINING, acting_agent="aetheria")
    assert r.status == CoordStatus.REFINING


def test_state_transition_refining_to_ready(store):
    node = store.create_node(board=CoordBoard.BLUEPRINT, owner="scotty", content="A")
    store.update_status(node.id, CoordStatus.REFINING, acting_agent="aetheria")
    r = store.update_status(node.id, CoordStatus.READY, acting_agent="aetheria")
    assert r.status == CoordStatus.READY


def test_invalid_backward_transition_ready_to_refining_rejected(store):
    node = store.create_node(board=CoordBoard.BLUEPRINT, owner="scotty", content="A")
    store.update_status(node.id, CoordStatus.REFINING, acting_agent="aetheria")
    store.update_status(node.id, CoordStatus.READY, acting_agent="aetheria")
    with pytest.raises(CoordinationError, match="invalid transition"):
        store.update_status(node.id, CoordStatus.REFINING, acting_agent="aetheria")


def test_skipping_state_open_to_ready_rejected(store):
    """Open cannot jump straight to Ready — must go through Refining."""
    node = store.create_node(board=CoordBoard.SIGNAL, owner="vett", content="A")
    with pytest.raises(CoordinationError, match="invalid transition"):
        store.update_status(node.id, CoordStatus.READY, acting_agent="aetheria")


def test_update_status_to_archived_rejected_with_helpful_message(store):
    """update_status cannot do archive — must use archive_node with a lesson."""
    node = store.create_node(board=CoordBoard.SIGNAL, owner="vett", content="A")
    with pytest.raises(CoordinationError, match="archive_node"):
        store.update_status(node.id, CoordStatus.ARCHIVED, acting_agent="aetheria")


def test_open_can_go_directly_to_archived_via_archive_node(store):
    """An Open node can be dropped (archived) without going through Refining/Ready.
    Useful for noise dismissal on Signal board."""
    node = store.create_node(board=CoordBoard.SIGNAL, owner="vett", content="noise")
    r = store.archive_node(node.id, lesson_learned_content="dismissed as noise",
                            acting_agent="aetheria")
    assert r.status == CoordStatus.ARCHIVED


def test_update_status_on_missing_node_raises(store):
    with pytest.raises(CoordinationError, match="not found"):
        store.update_status("does-not-exist", CoordStatus.REFINING, acting_agent="aetheria")


# ─── Archive + Lesson Learned ───────────────────────────────────────────────

def test_archive_writes_lesson_learned_lattice_node(store, lattice_path):
    coord = store.create_node(board=CoordBoard.BLUEPRINT, owner="scotty", content="plan X")
    store.update_status(coord.id, CoordStatus.REFINING, acting_agent="aetheria")
    store.update_status(coord.id, CoordStatus.READY, acting_agent="aetheria")
    r = store.archive_node(
        coord.id,
        lesson_learned_content="X turned out to need a different approach because Y",
        acting_agent="aetheria",
    )
    assert r.archived_lesson_id is not None
    # Lesson Learned node persists in the lattice with the right type
    con = sqlite3.connect(str(lattice_path))
    con.row_factory = sqlite3.Row
    lesson = con.execute(
        "SELECT type, content, agent, provenance FROM nodes WHERE id = ?",
        (r.archived_lesson_id,),
    ).fetchone()
    con.close()
    assert lesson is not None
    assert lesson["type"] == LESSON_LEARNED_NODE_TYPE
    assert lesson["agent"] == "aetheria"
    assert "different approach" in lesson["content"]
    import json
    prov = json.loads(lesson["provenance"])
    assert prov["archived_coord_node_id"] == coord.id
    assert prov["from_board"] == CoordBoard.BLUEPRINT.value


def test_archive_requires_lesson_content(store):
    node = store.create_node(board=CoordBoard.SIGNAL, owner="vett", content="A")
    with pytest.raises(CoordinationError, match="non-empty"):
        store.archive_node(node.id, lesson_learned_content="", acting_agent="aetheria")


def test_archive_idempotency_double_archive_rejected(store):
    """An already-Archived node cannot be archived twice — Archived is terminal."""
    node = store.create_node(board=CoordBoard.SIGNAL, owner="vett", content="A")
    store.archive_node(node.id, lesson_learned_content="learned",
                        acting_agent="aetheria")
    with pytest.raises(CoordinationError, match="already Archived"):
        store.archive_node(node.id, lesson_learned_content="again",
                            acting_agent="aetheria")


# ─── Cross-reference instrumentation ────────────────────────────────────────

def test_list_with_reading_agent_logs_references(store, lattice_path):
    """Every node returned in a reading_agent= read is logged for back-compute."""
    a = store.create_node(board=CoordBoard.SIGNAL, owner="vett", content="A")
    b = store.create_node(board=CoordBoard.SIGNAL, owner="vett", content="B")
    store.list_nodes(reading_agent="aetheria")
    con = sqlite3.connect(str(lattice_path))
    rows = con.execute(
        "SELECT referenced_node_id, source_agent FROM coord_references "
        "ORDER BY created_at ASC"
    ).fetchall()
    con.close()
    referenced_ids = [r[0] for r in rows]
    assert a.id in referenced_ids
    assert b.id in referenced_ids
    assert all(r[1] == "aetheria" for r in rows)


def test_list_without_reading_agent_does_not_log(store, lattice_path):
    """Plain reads (no reading_agent) shouldn't pollute coord_references."""
    store.create_node(board=CoordBoard.SIGNAL, owner="vett", content="A")
    store.list_nodes()  # no reading_agent
    con = sqlite3.connect(str(lattice_path))
    n = con.execute("SELECT COUNT(*) FROM coord_references").fetchone()[0]
    con.close()
    assert n == 0


def test_update_status_logs_acting_agent_reference(store, lattice_path):
    node = store.create_node(board=CoordBoard.SIGNAL, owner="vett", content="A")
    store.update_status(node.id, CoordStatus.REFINING, acting_agent="aetheria")
    con = sqlite3.connect(str(lattice_path))
    refs = con.execute(
        "SELECT source_agent FROM coord_references WHERE referenced_node_id = ?",
        (node.id,),
    ).fetchall()
    con.close()
    assert any(r[0] == "aetheria" for r in refs)


def test_reference_count_returns_total(store):
    a = store.create_node(board=CoordBoard.SIGNAL, owner="vett", content="A")
    # State transitions count as references
    store.update_status(a.id, CoordStatus.REFINING, acting_agent="aetheria")
    store.update_status(a.id, CoordStatus.READY, acting_agent="aetheria")
    assert store.reference_count(a.id) >= 2


def test_create_with_lattice_ref_logs_initial_reference(store, lattice_path):
    """When a coord node is created with lattice_ref, the link is logged."""
    ref = "some-lattice-uuid"
    coord = store.create_node(
        board=CoordBoard.BLUEPRINT, owner="scotty",
        content="refining X", lattice_ref=ref,
    )
    con = sqlite3.connect(str(lattice_path))
    rows = con.execute(
        "SELECT source_node_id, referenced_node_id FROM coord_references "
        "WHERE referenced_node_id = ?",
        (ref,),
    ).fetchall()
    con.close()
    assert len(rows) == 1
    assert rows[0][0] == coord.id


# ─── Provenance round-trip ──────────────────────────────────────────────────

def test_provenance_survives_round_trip_through_db(store):
    """The fields we stuff into provenance JSON (board/status/owner/lattice_ref)
    must round-trip cleanly when we read back from the DB."""
    ref = "lattice-thingy"
    a = store.create_node(
        board=CoordBoard.BLUEPRINT, owner="scotty",
        content="refining X", lattice_ref=ref,
    )
    got = store.get_node(a.id)
    assert got.board == CoordBoard.BLUEPRINT
    assert got.status == CoordStatus.OPEN
    assert got.owner == "scotty"
    assert got.lattice_ref == ref


# ─── delivery_states_for_actor (the receipt mirror) ──────────────────────────

def test_delivery_states_for_actor_reflects_triggered_agents(store):
    """A node Vett created and that reached Aetheria reads 'received'; one not
    yet routed reads 'not yet received'; a routing error reads 'delivery failed'."""
    import sqlite3 as _sq
    received = store.create_node(board=CoordBoard.SIGNAL, owner="vett", content="lead A")
    pending = store.create_node(board=CoordBoard.SIGNAL, owner="vett", content="lead B")
    errored = store.create_node(board=CoordBoard.SIGNAL, owner="vett", content="lead C")
    # create_node logs node_created rows with triggered_agents=NULL; simulate the
    # worker filling them in post-routing.
    with _sq.connect(store.db_path) as conn:
        conn.execute("UPDATE coord_event_log SET triggered_agents='aetheria' WHERE node_id=?", (received.id,))
        conn.execute("UPDATE coord_event_log SET triggered_agents='aetheria=ERROR:AgentLoopError' WHERE node_id=?", (errored.id,))
        # pending left NULL

    states = store.delivery_states_for_actor("vett")
    assert states[received.id] == "sent to aetheria, received"
    assert states[pending.id] == "sent, not yet received"
    assert states[errored.id] == "sent to aetheria, delivery failed"


def test_delivery_states_only_includes_this_actor(store):
    mine = store.create_node(board=CoordBoard.SIGNAL, owner="vett", content="vett node")
    store.create_node(board=CoordBoard.BLUEPRINT, owner="aetheria", content="aetheria node")
    states = store.delivery_states_for_actor("vett")
    assert mine.id in states
    assert len(states) == 1  # aetheria's node not in vett's outbound view


# ─── notify flag: quiet "park" create (Mission Control human path) ───────────

def test_create_node_notify_false_skips_event(store):
    """notify=False parks an item on the board WITHOUT emitting a routable
    event, so the webhook router never sees it and no agent is triggered.
    The node itself is still persisted and visible on the board."""
    node = store.create_node(
        board=CoordBoard.BLUEPRINT, owner="jon",
        content="park this spec until the hardware lands", notify=False,
    )
    with sqlite3.connect(str(store.db_path)) as conn:
        rows = conn.execute(
            "SELECT id FROM coord_event_log WHERE node_id = ?", (node.id,)
        ).fetchall()
    assert rows == []                            # no event → no routing → no trigger
    assert store.get_node(node.id) is not None   # node still parked on the board


def test_create_node_notify_true_emits_event_by_default(store):
    """Default (notify=True) still emits NODE_CREATED — the existing
    agent-driven create path must be unchanged."""
    node = store.create_node(
        board=CoordBoard.SIGNAL, owner="jon", content="note to the team",
    )
    with sqlite3.connect(str(store.db_path)) as conn:
        rows = conn.execute(
            "SELECT kind FROM coord_event_log WHERE node_id = ?", (node.id,)
        ).fetchall()
    assert ("node_created",) in rows
