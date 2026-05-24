"""Tests for soveryn.memory.conversation_store. Uses tmp_path — never production."""

import pytest
from soveryn.memory.conversation_store import (
    ConversationStore, ConversationStoreError, Session, Turn, VALID_ROLES,
)


@pytest.fixture
def store(tmp_path):
    return ConversationStore(tmp_path / "test_conv.db")


def test_new_session_returns_uuid(store):
    sid = store.new_session("aetheria")
    assert isinstance(sid, str) and len(sid) == 36


def test_new_session_creates_meta_row(store):
    sid = store.new_session("aetheria", title="hello")
    sessions = store.list_sessions(agent="aetheria")
    assert len(sessions) == 1
    assert sessions[0].session_id == sid
    assert sessions[0].title == "hello"


def test_save_turn_preserves_order(store):
    sid = store.new_session("aetheria")
    store.save_turn(sid, "aetheria", "user", "first")
    store.save_turn(sid, "aetheria", "assistant", "second")
    store.save_turn(sid, "aetheria", "user", "third")
    history = store.load_history(sid)
    assert [t.content for t in history] == ["first", "second", "third"]
    assert [t.role for t in history] == ["user", "assistant", "user"]


def test_save_turn_default_source_is_direct(store):
    sid = store.new_session("aetheria")
    store.save_turn(sid, "aetheria", "user", "hi")
    assert store.load_history(sid)[0].source == "direct"


def test_save_turn_custom_source(store):
    sid = store.new_session("aetheria")
    store.save_turn(sid, "aetheria", "user", "hi", source="mobile")
    assert store.load_history(sid)[0].source == "mobile"


@pytest.mark.parametrize("bad_role", ["narrator", "Aetheria", "USER", "", "robot"])
def test_save_turn_rejects_unknown_role(store, bad_role):
    sid = store.new_session("aetheria")
    with pytest.raises(ConversationStoreError, match="role="):
        store.save_turn(sid, "aetheria", bad_role, "hi")


@pytest.mark.parametrize("role", ["user", "assistant", "system", "tool"])
def test_save_turn_accepts_valid_roles(store, role):
    sid = store.new_session("aetheria")
    store.save_turn(sid, "aetheria", role, "x")
    assert store.load_history(sid)[0].role == role


def test_list_sessions_filtered_by_agent(store):
    a_id = store.new_session("aetheria")
    v_id = store.new_session("vett")
    aetheria_sessions = store.list_sessions(agent="aetheria")
    assert [s.session_id for s in aetheria_sessions] == [a_id]
    vett_sessions = store.list_sessions(agent="vett")
    assert [s.session_id for s in vett_sessions] == [v_id]


def test_list_sessions_no_filter_returns_all(store):
    store.new_session("aetheria")
    store.new_session("vett")
    assert len(store.list_sessions()) == 2


def test_delete_session_removes_meta_and_turns(store):
    sid = store.new_session("aetheria")
    store.save_turn(sid, "aetheria", "user", "x")
    store.delete_session(sid)
    assert store.list_sessions(agent="aetheria") == ()
    assert store.load_history(sid) == ()


def test_update_title_touches_updated_at(store):
    import time
    sid = store.new_session("aetheria", title="a")
    original_updated = store.list_sessions(agent="aetheria")[0].updated_at
    time.sleep(0.01)
    store.update_title(sid, "b")
    new_updated = store.list_sessions(agent="aetheria")[0].updated_at
    assert new_updated > original_updated
    assert store.list_sessions(agent="aetheria")[0].title == "b"


def test_save_turn_updates_meta_updated_at(store):
    import time
    sid = store.new_session("aetheria")
    orig = store.list_sessions(agent="aetheria")[0].updated_at
    time.sleep(0.01)
    store.save_turn(sid, "aetheria", "user", "hi")
    new = store.list_sessions(agent="aetheria")[0].updated_at
    assert new > orig


def test_schema_includes_fts_table(store):
    """Production depends on conversations_fts being maintained."""
    import sqlite3
    conn = sqlite3.connect(str(store.db_path))
    rows = conn.execute("SELECT name FROM sqlite_master WHERE name='conversations_fts'").fetchall()
    conn.close()
    assert rows, "conversations_fts virtual table missing"


def test_fts_trigger_populates_index(store):
    """Inserting a turn should populate conversations_fts via trigger."""
    import sqlite3
    sid = store.new_session("aetheria")
    store.save_turn(sid, "aetheria", "user", "unique-phrase-xyzzy")
    conn = sqlite3.connect(str(store.db_path))
    rows = conn.execute(
        "SELECT rowid FROM conversations_fts WHERE content MATCH ?",
        ("xyzzy",),
    ).fetchall()
    conn.close()
    assert len(rows) == 1


def test_store_never_writes_outside_injected_path(store, tmp_path):
    assert str(store.db_path).startswith(str(tmp_path))


def test_valid_roles_constant():
    assert VALID_ROLES == {"user", "assistant", "system", "tool"}
