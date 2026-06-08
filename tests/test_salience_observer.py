"""Tests for soveryn.platform.salience.observer. Uses tmp_path — never production.

Covers Task 3 of the Salience Engine plan: the inline observer that scores
turns on save, daemon-session filtering, non-fatal contract, and the
ConversationStore wire-up.
"""

from __future__ import annotations
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from soveryn.memory.conversation_store import ConversationStore
from soveryn.platform.salience.observer import (
    DAEMON_SESSION_TITLE_PREFIXES,
    SalienceObserver,
)
from soveryn.platform.salience.store import (
    STATUS_PENDING,
    create_buffer_table,
    pending_candidates_since,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _all_pending(salience_db: Path):
    """All pending candidates since the epoch — handy assertion target."""
    return pending_candidates_since(
        salience_db, since=datetime(1970, 1, 1), limit=1000
    )


def _seed_meta(conv_db: Path, session_id: str, title: str | None) -> None:
    """Insert a conversation_meta row directly so the observer can read it."""
    conv_db.parent.mkdir(parents=True, exist_ok=True)
    # Reuse ConversationStore's schema bootstrap.
    ConversationStore(conv_db)
    now = datetime.now().isoformat()
    with sqlite3.connect(str(conv_db)) as con:
        con.execute(
            "INSERT OR REPLACE INTO conversation_meta "
            "(session_id, agent, title, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, "aetheria", title, now, now),
        )


# ─── Observer in isolation ──────────────────────────────────────────────────


def test_observer_writes_candidate_when_hard_lock_marker_present(tmp_path):
    salience_db = tmp_path / "salience.db"
    create_buffer_table(salience_db)
    observer = SalienceObserver(salience_db=salience_db)
    observer.on_turn_saved(
        session_id="sess-1",
        turn_rowid=1,
        role="user",
        content="The plan is locked. Ship it.",
    )
    pending = _all_pending(salience_db)
    assert len(pending) == 1
    cats = {m.category for m in pending[0].markers}
    markers = {m.marker for m in pending[0].markers}
    assert "hard_lock" in cats
    assert "locked" in markers
    assert pending[0].status == STATUS_PENDING


def test_observer_does_not_write_when_no_marker_hits(tmp_path):
    salience_db = tmp_path / "salience.db"
    create_buffer_table(salience_db)
    observer = SalienceObserver(salience_db=salience_db)
    observer.on_turn_saved(
        session_id="sess-1",
        turn_rowid=1,
        role="user",
        content="hi how are you",
    )
    assert _all_pending(salience_db) == []


def test_observer_swallows_exceptions(tmp_path):
    # Parent dir doesn't exist AND we never bootstrapped the schema —
    # insert_candidate would blow up if it ran. Observer must not raise.
    salience_db = tmp_path / "does" / "not" / "exist" / "salience.db"
    observer = SalienceObserver(salience_db=salience_db)
    observer.on_turn_saved(
        session_id="sess-1",
        turn_rowid=1,
        role="user",
        content="The plan is locked.",
    )  # no exception escapes


def test_observer_filters_heartbeat_sessions(tmp_path):
    salience_db = tmp_path / "salience.db"
    conv_db = tmp_path / "conv.db"
    create_buffer_table(salience_db)
    _seed_meta(conv_db, "sess-heart", "[heartbeat] aetheria")
    observer = SalienceObserver(salience_db=salience_db, conv_db=conv_db)
    observer.on_turn_saved(
        session_id="sess-heart",
        turn_rowid=1,
        role="user",
        content="The plan is locked.",
    )
    assert _all_pending(salience_db) == []


def test_observer_filters_signal_sessions(tmp_path):
    salience_db = tmp_path / "salience.db"
    conv_db = tmp_path / "conv.db"
    create_buffer_table(salience_db)
    _seed_meta(conv_db, "sess-sig", "[signal] +19102489392")
    observer = SalienceObserver(salience_db=salience_db, conv_db=conv_db)
    observer.on_turn_saved(
        session_id="sess-sig",
        turn_rowid=1,
        role="user",
        content="The plan is locked.",
    )
    assert _all_pending(salience_db) == []


def test_observer_filters_dream_sessions(tmp_path):
    salience_db = tmp_path / "salience.db"
    conv_db = tmp_path / "conv.db"
    create_buffer_table(salience_db)
    _seed_meta(conv_db, "sess-dream", "[dream] consolidation")
    observer = SalienceObserver(salience_db=salience_db, conv_db=conv_db)
    observer.on_turn_saved(
        session_id="sess-dream",
        turn_rowid=1,
        role="user",
        content="The plan is locked.",
    )
    assert _all_pending(salience_db) == []


def test_observer_does_not_filter_when_conv_db_omitted(tmp_path):
    # No conv_db → can't read titles, so daemon-prefix filtering can't
    # apply. A heartbeat-titled session still gets scored.
    salience_db = tmp_path / "salience.db"
    create_buffer_table(salience_db)
    observer = SalienceObserver(salience_db=salience_db)
    observer.on_turn_saved(
        session_id="sess-heart",
        turn_rowid=1,
        role="user",
        content="The plan is locked.",
    )
    assert len(_all_pending(salience_db)) == 1


def test_daemon_prefixes_constant_is_tuple():
    # Tweakable from one place — and must remain immutable so production
    # imports can rely on identity-stable membership checks.
    assert isinstance(DAEMON_SESSION_TITLE_PREFIXES, tuple)
    assert "[heartbeat]" in DAEMON_SESSION_TITLE_PREFIXES
    assert "[signal]" in DAEMON_SESSION_TITLE_PREFIXES
    assert "[patrol]" in DAEMON_SESSION_TITLE_PREFIXES
    assert "[webhook]" in DAEMON_SESSION_TITLE_PREFIXES
    assert "[dream]" in DAEMON_SESSION_TITLE_PREFIXES


# ─── ConversationStore integration ──────────────────────────────────────────


def test_conv_store_calls_observer_on_save_turn(tmp_path):
    salience_db = tmp_path / "salience.db"
    create_buffer_table(salience_db)
    conv_db = tmp_path / "conv.db"
    observer = SalienceObserver(salience_db=salience_db, conv_db=conv_db)
    store = ConversationStore(conv_db, observer=observer)
    sid = store.new_session("aetheria", title="conv title")
    store.save_turn(sid, "aetheria", "user", "The plan is locked. Ship it.")
    pending = _all_pending(salience_db)
    assert len(pending) == 1
    assert pending[0].session_id == sid


def test_conv_store_no_observer_works_normally(tmp_path):
    # Backward compat: no observer kwarg → behavior unchanged.
    store = ConversationStore(tmp_path / "conv.db")
    sid = store.new_session("aetheria")
    store.save_turn(sid, "aetheria", "user", "The plan is locked.")
    store.save_turn(sid, "aetheria", "assistant", "ack")
    history = store.load_history(sid)
    assert [t.role for t in history] == ["user", "assistant"]
    assert [t.content for t in history] == ["The plan is locked.", "ack"]


def test_conv_store_observer_exception_does_not_break_save(tmp_path):
    class BrokenObserver:
        def on_turn_saved(self, **kwargs):
            raise RuntimeError("boom")

    store = ConversationStore(tmp_path / "conv.db", observer=BrokenObserver())
    sid = store.new_session("aetheria")
    # Should not raise.
    store.save_turn(sid, "aetheria", "user", "hello")
    history = store.load_history(sid)
    assert len(history) == 1
    assert history[0].content == "hello"


def test_conv_store_observer_receives_correct_rowid(tmp_path):
    received: list[dict] = []

    class CaptureObserver:
        def on_turn_saved(self, **kwargs):
            received.append(kwargs)

    store = ConversationStore(tmp_path / "conv.db", observer=CaptureObserver())
    sid = store.new_session("aetheria")
    store.save_turn(sid, "aetheria", "user", "one")
    store.save_turn(sid, "aetheria", "assistant", "two")
    store.save_turn(sid, "aetheria", "user", "three")
    store.save_turn(sid, "aetheria", "assistant", "four")
    assert len(received) == 4
    assert received[3]["turn_rowid"] == 4
    assert received[3]["role"] == "assistant"
    assert received[3]["content"] == "four"
    assert received[3]["session_id"] == sid


def test_observer_called_for_assistant_turns_too(tmp_path):
    salience_db = tmp_path / "salience.db"
    create_buffer_table(salience_db)
    conv_db = tmp_path / "conv.db"
    observer = SalienceObserver(salience_db=salience_db, conv_db=conv_db)
    store = ConversationStore(conv_db, observer=observer)
    sid = store.new_session("aetheria", title="conv title")
    # Synthesis marker — assistant-only category.
    store.save_turn(
        sid, "aetheria", "assistant",
        "I think the realization is that the loop was the amplifier.",
    )
    pending = _all_pending(salience_db)
    assert len(pending) == 1
    assert pending[0].turn_role == "assistant"
    cats = {m.category for m in pending[0].markers}
    assert "synthesis" in cats
