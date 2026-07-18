"""Tests for the one-time surgical heartbeat re-tag migration.

The module under test lives at a dated filename
(scripts/migrations/2026-07-18-retag-heartbeat-source.py) which is not a
valid Python module path, so it is loaded via importlib.util from its
file path rather than a normal import statement.
"""
import importlib.util
import sqlite3
from pathlib import Path

MODULE_PATH = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "migrations"
    / "2026-07-18-retag-heartbeat-source.py"
)


def _load_migration_module():
    spec = importlib.util.spec_from_file_location("retag_heartbeat_source", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _mk(conn):
    conn.executescript("""
      CREATE TABLE conversation_meta(session_id TEXT, agent TEXT, title TEXT, created_at TEXT, updated_at TEXT);
      CREATE TABLE conversations(session_id TEXT, agent TEXT, role TEXT, content TEXT, timestamp TEXT, source TEXT, finish_reason TEXT);
    """)
    conn.execute("INSERT INTO conversation_meta VALUES('hb','aetheria','[heartbeat] aetheria','t','t')")
    conn.execute("INSERT INTO conversation_meta VALUES('real','aetheria','morning chat','t','t')")
    # heartbeat session: pulse pair, then a REAL human interjection pair, then another pulse pair
    rows = [
        ('hb', 'aetheria', 'user', '[HEARTBEAT] pulse 1', 't1', 'direct', None),
        ('hb', 'aetheria', 'assistant', 'I spent this pulse...', 't2', 'direct', 'stop'),
        ('hb', 'aetheria', 'user', 'hey are you ok?', 't3', 'direct', None),        # REAL — must stay direct
        ('hb', 'aetheria', 'assistant', 'yes, I am here', 't4', 'direct', 'stop'),  # REAL response — must stay direct
        ('hb', 'aetheria', 'user', '[HEARTBEAT] pulse 2', 't5', 'direct', None),
        ('hb', 'aetheria', 'assistant', 'I spent this pulse...2', 't6', 'direct', 'stop'),
        ('real', 'aetheria', 'user', 'hello', 't7', 'direct', None),                # different session — untouched
        ('real', 'aetheria', 'assistant', 'hi', 't8', 'direct', 'stop'),
    ]
    conn.executemany("INSERT INTO conversations VALUES(?,?,?,?,?,?,?)", rows)
    conn.commit()


def test_retag_only_heartbeat_pulse_turns():
    module = _load_migration_module()
    conn = sqlite3.connect(":memory:")
    _mk(conn)

    res = module.retag_heartbeat_turns(conn)
    conn.commit()

    got = conn.execute("SELECT content, source FROM conversations ORDER BY timestamp").fetchall()
    src = {c: s for c, s in got}

    assert src['[HEARTBEAT] pulse 1'] == 'heartbeat'
    assert src['I spent this pulse...'] == 'heartbeat'
    assert src['hey are you ok?'] == 'direct'       # real turn preserved
    assert src['yes, I am here'] == 'direct'        # real response preserved
    assert src['[HEARTBEAT] pulse 2'] == 'heartbeat'
    assert src['I spent this pulse...2'] == 'heartbeat'
    assert src['hello'] == 'direct'                 # other session untouched
    assert src['hi'] == 'direct'

    # 4 heartbeat rows retagged (pulse1 user+asst, pulse2 user+asst); of the rows
    # IN SCOPE (heartbeat-titled session only), 2 remain direct (the real
    # interjection pair). The 'real' session is out of scope entirely — it is
    # never evaluated, so it does not factor into either count.
    assert res == {"retagged": 4, "left_direct": 2}


def test_retag_is_idempotent():
    module = _load_migration_module()
    conn = sqlite3.connect(":memory:")
    _mk(conn)

    first = module.retag_heartbeat_turns(conn)
    conn.commit()
    second = module.retag_heartbeat_turns(conn)
    conn.commit()

    assert first == {"retagged": 4, "left_direct": 2}
    assert second == {"retagged": 0, "left_direct": 2}

    got = conn.execute("SELECT content, source FROM conversations ORDER BY timestamp").fetchall()
    src = {c: s for c, s in got}
    assert src['[HEARTBEAT] pulse 1'] == 'heartbeat'
    assert src['I spent this pulse...'] == 'heartbeat'
    assert src['hey are you ok?'] == 'direct'
    assert src['yes, I am here'] == 'direct'
