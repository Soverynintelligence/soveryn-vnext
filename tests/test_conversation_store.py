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


def test_load_history_strips_think_markup_from_persisted_rows(store):
    import sqlite3
    sid = store.new_session("aetheria")
    with sqlite3.connect(str(store.db_path)) as conn:
        conn.execute(
            "INSERT INTO conversations (session_id, agent, role, content, timestamp, source) VALUES (?, ?, ?, ?, datetime('now'), ?)",
            (sid, "aetheria", "assistant", "<think>scratch</think>final", "direct"),
        )
        conn.commit()
    history = store.load_history(sid)
    assert [t.content for t in history] == ["final"]


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


def test_fts_trigger_populates_index_on_insert(store):
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


def test_fts_trigger_removes_index_on_delete_session(store):
    """delete_session DELETEs from conversations — FTS must drop the row too."""
    import sqlite3
    sid = store.new_session("aetheria")
    store.save_turn(sid, "aetheria", "user", "phrase-deletion-marker-abcdef")
    # Confirm present first
    conn = sqlite3.connect(str(store.db_path))
    before = conn.execute(
        "SELECT rowid FROM conversations_fts WHERE content MATCH ?",
        ("abcdef",),
    ).fetchall()
    conn.close()
    assert len(before) == 1
    # Now delete the whole session
    store.delete_session(sid)
    conn = sqlite3.connect(str(store.db_path))
    after = conn.execute(
        "SELECT rowid FROM conversations_fts WHERE content MATCH ?",
        ("abcdef",),
    ).fetchall()
    conn.close()
    assert len(after) == 0, "FTS still has stale row after session deletion"


def test_fts_trigger_syncs_on_update(store):
    """UPDATE-trigger should rewrite the FTS row when the underlying content changes.

    No public API issues UPDATEs (the store is append-only), but production
    occasionally runs raw UPDATEs (e.g. content scrubs). Use raw SQL here to
    verify the trigger is wired correctly — that's the kind of schema detail
    that breaks silently otherwise.
    """
    import sqlite3
    sid = store.new_session("aetheria")
    store.save_turn(sid, "aetheria", "user", "phrase-old-foo-aaaaaa")
    with sqlite3.connect(str(store.db_path)) as conn:
        conn.execute(
            "UPDATE conversations SET content = ? WHERE session_id = ?",
            ("phrase-new-bar-bbbbbb", sid),
        )
        conn.commit()
    with sqlite3.connect(str(store.db_path)) as conn:
        old_hits = conn.execute(
            "SELECT rowid FROM conversations_fts WHERE content MATCH ?",
            ("aaaaaa",),
        ).fetchall()
        new_hits = conn.execute(
            "SELECT rowid FROM conversations_fts WHERE content MATCH ?",
            ("bbbbbb",),
        ).fetchall()
    assert len(old_hits) == 0, "FTS still indexes the old content after UPDATE"
    assert len(new_hits) == 1, "FTS missing the new content after UPDATE"


def test_store_never_writes_outside_injected_path(store, tmp_path):
    assert str(store.db_path).startswith(str(tmp_path))


def test_valid_roles_constant():
    assert VALID_ROLES == {"user", "assistant", "system", "tool"}


def test_get_session_returns_session_for_existing_id(store):
    sid = store.new_session("aetheria", title="hello")
    session = store.get_session(sid)
    assert session is not None
    assert session.session_id == sid
    assert session.agent == "aetheria"
    assert session.title == "hello"


def test_get_session_returns_none_for_missing_id(store):
    assert store.get_session("does-not-exist") is None
