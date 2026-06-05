"""Tests for soveryn.platform.lattice.legacy — constants and schema migrations."""


def test_layer_dream_constant_exists():
    from soveryn.platform.lattice.legacy import LAYER_DREAM
    assert LAYER_DREAM == "dream"


def test_dream_log_dry_run_column_added_idempotently(tmp_path):
    """Both fresh DBs and pre-existing dream_log tables (the migrated
    legacy 9608 rows) must end up with the dry_run column without error."""
    import sqlite3
    from soveryn.platform.lattice.legacy import LatticeStore

    # Case A: fresh DB
    db_a = tmp_path / "fresh.db"
    LatticeStore(db_a)
    with sqlite3.connect(str(db_a)) as con:
        con.row_factory = sqlite3.Row
        cols = {r["name"] for r in con.execute(
            "PRAGMA table_info(dream_log)"
        ).fetchall()}
        assert "dry_run" in cols

    # Case B: pre-existing DB with the older dream_log shape (no dry_run)
    db_b = tmp_path / "legacy.db"
    with sqlite3.connect(str(db_b)) as con:
        con.execute("""
            CREATE TABLE dream_log (
                id TEXT PRIMARY KEY,
                trigger TEXT NOT NULL,
                agent TEXT NOT NULL,
                ran_at TEXT NOT NULL
            )
        """)
    # Now initialize through LatticeStore — should add the column.
    LatticeStore(db_b)
    with sqlite3.connect(str(db_b)) as con:
        con.row_factory = sqlite3.Row
        cols = {r["name"] for r in con.execute(
            "PRAGMA table_info(dream_log)"
        ).fetchall()}
        assert "dry_run" in cols


def test_record_direct_communication_edge_writes_node_and_typed_edge_for_execute(tmp_path):
    """A direct-communication record creates a real lattice node for the
    direct message AND an edge tying it to the coord node, with
    relationship='direct_command' for mode='execute'.

    Regression for the DAC-T8 bug: earlier signature passed a bare
    session_id as message_node_id, which silently failed the edges
    table's FK constraint in production. New signature creates the
    node first so the FK is satisfied."""
    import sqlite3
    from soveryn.platform.lattice.legacy import (
        LatticeStore, LAYER_PRIVATE, record_direct_communication_edge,
    )
    db = tmp_path / "lattice.db"
    store = LatticeStore(db)
    coord_node_id = store.write_node(agent="aetheria", content="coord task X",
                                     layer=LAYER_PRIVATE)

    message_node_id, edge_id = record_direct_communication_edge(
        store=store,
        coord_node_id=coord_node_id,
        sender_agent="aetheria",
        target_agent="vett",
        session_id="sess-abc",
        mode="execute",
        message_head="audit the friction nodes",
    )

    # Node was written and is queryable
    with sqlite3.connect(str(db)) as con:
        node_row = con.execute(
            "SELECT type, agent, layer, content FROM nodes WHERE id = ?",
            (message_node_id,),
        ).fetchone()
    assert node_row is not None
    node_type, agent, layer, content = node_row
    assert node_type == "direct_message"
    assert agent == "aetheria"
    assert layer == LAYER_PRIVATE
    assert "vett" in content
    assert "execute" in content
    assert "sess-abc" in content
    assert "audit the friction nodes" in content

    # Edge ties message node → coord node with correct relationship
    with sqlite3.connect(str(db)) as con:
        edge_row = con.execute(
            "SELECT id, source_id, target_id, relationship FROM edges WHERE id = ?",
            (edge_id,),
        ).fetchone()
    assert edge_row is not None
    eid, source_id, target_id, relationship = edge_row
    assert eid == edge_id
    assert source_id == message_node_id
    assert target_id == coord_node_id
    assert relationship == "direct_command"


def test_record_direct_communication_edge_query_mode_writes_direct_query(tmp_path):
    """mode='query' → relationship='direct_query'."""
    import sqlite3
    from soveryn.platform.lattice.legacy import (
        LatticeStore, LAYER_PRIVATE, record_direct_communication_edge,
    )
    db = tmp_path / "lattice.db"
    store = LatticeStore(db)
    coord_id = store.write_node(agent="aetheria", content="coord", layer=LAYER_PRIVATE)
    _, edge_id = record_direct_communication_edge(
        store=store, coord_node_id=coord_id,
        sender_agent="aetheria", target_agent="scotty",
        session_id="sess-xyz", mode="query", message_head="raw obs please",
    )
    with sqlite3.connect(str(db)) as con:
        rel = con.execute(
            "SELECT relationship FROM edges WHERE id = ?", (edge_id,),
        ).fetchone()[0]
    assert rel == "direct_query"


def test_record_direct_communication_edge_rejects_invalid_mode(tmp_path):
    """Only 'execute' and 'query' are accepted."""
    import pytest
    from soveryn.platform.lattice.legacy import (
        LatticeStore, LAYER_PRIVATE, record_direct_communication_edge,
    )
    store = LatticeStore(tmp_path / "lattice.db")
    coord_id = store.write_node(agent="aetheria", content="c", layer=LAYER_PRIVATE)
    with pytest.raises(ValueError, match="execute.*query|mode"):
        record_direct_communication_edge(
            store=store, coord_node_id=coord_id,
            sender_agent="aetheria", target_agent="vett",
            session_id="sess-1", mode="other",
        )


def test_record_direct_communication_edge_satisfies_fk_with_real_nodes(tmp_path):
    """End-to-end FK regression: the production bug was that session_id was
    passed as a bare uuid not present in the nodes table, causing a silent
    IntegrityError. The new node-then-edge structure satisfies the FK by
    construction. Pin this so the regression can't drift back."""
    import sqlite3
    from soveryn.platform.lattice.legacy import (
        LatticeStore, LAYER_PRIVATE, record_direct_communication_edge,
    )
    db = tmp_path / "lattice.db"
    store = LatticeStore(db)
    coord_id = store.write_node(agent="aetheria", content="coord", layer=LAYER_PRIVATE)

    # Three direct messages with arbitrary session ids that are NOT in nodes
    for i, session in enumerate(["s1", "s2", "s3"]):
        record_direct_communication_edge(
            store=store, coord_node_id=coord_id,
            sender_agent="aetheria", target_agent="vett",
            session_id=session, mode="execute", message_head=f"msg {i}",
        )

    # All three edges landed (no silent FK failures)
    with sqlite3.connect(str(db)) as con:
        edge_count = con.execute(
            "SELECT COUNT(*) FROM edges WHERE relationship = 'direct_command'"
        ).fetchone()[0]
        node_count = con.execute(
            "SELECT COUNT(*) FROM nodes WHERE type = 'direct_message'"
        ).fetchone()[0]
    assert edge_count == 3
    assert node_count == 3
