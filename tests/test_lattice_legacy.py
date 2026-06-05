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


def test_record_direct_communication_edge_writes_typed_edge_for_execute(tmp_path):
    """A direct-communication edge ties a message node to a coord node with
    relationship='direct_command' for mode='execute'."""
    import sqlite3
    from soveryn.platform.lattice.legacy import (
        LatticeStore, LAYER_PRIVATE, record_direct_communication_edge,
    )
    db = tmp_path / "lattice.db"
    store = LatticeStore(db)
    coord_node_id = store.write_node(agent="aetheria", content="coord task X",
                                     layer=LAYER_PRIVATE)
    msg_node_id = store.write_node(agent="aetheria", content="do Y",
                                   layer=LAYER_PRIVATE)

    edge_id = record_direct_communication_edge(
        store=store,
        coord_node_id=coord_node_id,
        message_node_id=msg_node_id,
        mode="execute",
    )

    assert isinstance(edge_id, str)
    with sqlite3.connect(str(db)) as con:
        rows = con.execute(
            "SELECT id, source_id, target_id, relationship "
            "FROM edges WHERE id = ?",
            (edge_id,),
        ).fetchall()
    assert len(rows) == 1
    row_id, source_id, target_id, relationship = rows[0]
    assert row_id == edge_id
    assert source_id == msg_node_id
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
    msg_id = store.write_node(agent="aetheria", content="msg", layer=LAYER_PRIVATE)
    edge_id = record_direct_communication_edge(
        store=store, coord_node_id=coord_id, message_node_id=msg_id, mode="query",
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
    msg_id = store.write_node(agent="aetheria", content="m", layer=LAYER_PRIVATE)
    with pytest.raises(ValueError, match="execute.*query|mode"):
        record_direct_communication_edge(
            store=store, coord_node_id=coord_id, message_node_id=msg_id, mode="other",
        )
