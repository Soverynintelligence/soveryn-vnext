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
