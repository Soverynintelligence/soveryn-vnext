"""Tests for soveryn.platform.continuity.store.

Covers Task 3 of the Cross-Surface Continuity plan: querying OTHER
sessions in the configured window, filtering autonomous prefixes
(Signal explicitly passes), and pairing user/assistant turns while
ignoring tool/system rows. Pure data — formatting belongs to Task 4.
"""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timedelta

from soveryn.memory.conversation_store import ConversationStore
from soveryn.platform.continuity import (
    ContinuityConfig,
    PairedTurn,
    SessionTail,
    recent_cross_session_tails,
)


def _backdate_session(db_path, session_id: str, *, hours_ago: float) -> None:
    """Force conversation_meta.updated_at into the past via direct SQL.

    Mirrors the backdating pattern used in test_conversation_store.py —
    the public API touches updated_at on every write, so this is the
    only way to simulate a stale session in a unit test.
    """
    ts = (datetime.now() - timedelta(hours=hours_ago)).isoformat()
    with sqlite3.connect(str(db_path)) as con:
        con.execute(
            "UPDATE conversation_meta SET updated_at = ? WHERE session_id = ?",
            (ts, session_id),
        )


def test_returns_empty_when_no_other_sessions(tmp_path):
    """Only the current session exists — query returns ()."""
    store = ConversationStore(tmp_path / "conv.db")
    current = store.new_session("aetheria")
    store.save_turn(current, "aetheria", "user", "hello")
    cfg = ContinuityConfig()
    result = recent_cross_session_tails(
        store,
        agent="aetheria",
        current_session_id=current,
        config=cfg,
    )
    assert result == ()


def test_excludes_autonomous_prefix_sessions(tmp_path):
    """Heartbeat + dream sessions are filtered; signal session is kept."""
    store = ConversationStore(tmp_path / "conv.db")
    current = store.new_session("aetheria")

    heartbeat = store.new_session("aetheria", title="[heartbeat] aetheria")
    store.save_turn(heartbeat, "aetheria", "user", "tick")
    store.save_turn(heartbeat, "aetheria", "assistant", "tock")

    dream = store.new_session("aetheria", title="[dream] consolidation")
    store.save_turn(dream, "aetheria", "user", "consolidating")
    store.save_turn(dream, "aetheria", "assistant", "done")

    signal = store.new_session("aetheria", title="[signal] aetheria +19102489392")
    store.save_turn(signal, "aetheria", "user", "you there?")
    store.save_turn(signal, "aetheria", "assistant", "yes")

    cfg = ContinuityConfig()
    result = recent_cross_session_tails(
        store,
        agent="aetheria",
        current_session_id=current,
        config=cfg,
    )
    ids = [t.session_id for t in result]
    assert signal in ids
    assert heartbeat not in ids
    assert dream not in ids


def test_returns_last_paired_turns_in_order(tmp_path):
    """4 turns (u,a,u,a) with per_session_pairs=2 → both pairs in order."""
    store = ConversationStore(tmp_path / "conv.db")
    current = store.new_session("aetheria")
    other = store.new_session("aetheria")
    store.save_turn(other, "aetheria", "user", "first user")
    store.save_turn(other, "aetheria", "assistant", "first reply")
    store.save_turn(other, "aetheria", "user", "second user")
    store.save_turn(other, "aetheria", "assistant", "second reply")
    cfg = ContinuityConfig()
    result = recent_cross_session_tails(
        store,
        agent="aetheria",
        current_session_id=current,
        config=cfg,
        per_session_pairs=2,
    )
    assert len(result) == 1
    tail = result[0]
    assert tail.paired_turns == (
        PairedTurn(user="first user", assistant="first reply"),
        PairedTurn(user="second user", assistant="second reply"),
    )


def test_handles_in_flight_user_turn_without_assistant(tmp_path):
    """A user turn with no following assistant becomes PairedTurn(..., None)."""
    store = ConversationStore(tmp_path / "conv.db")
    current = store.new_session("aetheria")
    other = store.new_session("aetheria")
    store.save_turn(other, "aetheria", "user", "any reply?")
    cfg = ContinuityConfig()
    result = recent_cross_session_tails(
        store,
        agent="aetheria",
        current_session_id=current,
        config=cfg,
    )
    assert len(result) == 1
    assert result[0].paired_turns == (
        PairedTurn(user="any reply?", assistant=None),
    )


def test_respects_window_hours(tmp_path):
    """A session backdated past window_hours is excluded from the result."""
    store = ConversationStore(tmp_path / "conv.db")
    current = store.new_session("aetheria")

    fresh = store.new_session("aetheria")
    store.save_turn(fresh, "aetheria", "user", "fresh question")
    store.save_turn(fresh, "aetheria", "assistant", "fresh answer")

    stale = store.new_session("aetheria")
    store.save_turn(stale, "aetheria", "user", "stale question")
    store.save_turn(stale, "aetheria", "assistant", "stale answer")
    _backdate_session(tmp_path / "conv.db", stale, hours_ago=24)

    cfg = ContinuityConfig(window_hours=6)
    result = recent_cross_session_tails(
        store,
        agent="aetheria",
        current_session_id=current,
        config=cfg,
    )
    ids = [t.session_id for t in result]
    assert fresh in ids
    assert stale not in ids


def test_filters_tool_and_system_roles_from_paired_turns(tmp_path):
    """tool/system rows are skipped; only user/assistant survive into pairs."""
    store = ConversationStore(tmp_path / "conv.db")
    current = store.new_session("aetheria")
    other = store.new_session("aetheria")
    store.save_turn(other, "aetheria", "user", "u1")
    store.save_turn(other, "aetheria", "assistant", "a1")
    store.save_turn(other, "aetheria", "tool", '{"result": "irrelevant"}')
    store.save_turn(other, "aetheria", "user", "u2")
    store.save_turn(other, "aetheria", "system", "system note")
    store.save_turn(other, "aetheria", "assistant", "a2")
    cfg = ContinuityConfig()
    result = recent_cross_session_tails(
        store,
        agent="aetheria",
        current_session_id=current,
        config=cfg,
    )
    assert len(result) == 1
    assert result[0].paired_turns == (
        PairedTurn(user="u1", assistant="a1"),
        PairedTurn(user="u2", assistant="a2"),
    )


def test_per_session_pairs_limit_returns_last_n(tmp_path):
    """5 paired turns saved, per_session_pairs=2 → only the last 2 returned."""
    store = ConversationStore(tmp_path / "conv.db")
    current = store.new_session("aetheria")
    other = store.new_session("aetheria")
    for i in range(5):
        store.save_turn(other, "aetheria", "user", f"u{i}")
        store.save_turn(other, "aetheria", "assistant", f"a{i}")
    cfg = ContinuityConfig()
    result = recent_cross_session_tails(
        store,
        agent="aetheria",
        current_session_id=current,
        config=cfg,
        per_session_pairs=2,
    )
    assert len(result) == 1
    assert result[0].paired_turns == (
        PairedTurn(user="u3", assistant="a3"),
        PairedTurn(user="u4", assistant="a4"),
    )


def test_signal_session_passes_autonomous_filter(tmp_path):
    """Positive assertion: a [signal] session IS included in results."""
    store = ConversationStore(tmp_path / "conv.db")
    current = store.new_session("aetheria")
    signal = store.new_session("aetheria", title="[signal] aetheria +19102489392")
    store.save_turn(signal, "aetheria", "user", "from signal")
    store.save_turn(signal, "aetheria", "assistant", "ack")
    cfg = ContinuityConfig()
    result = recent_cross_session_tails(
        store,
        agent="aetheria",
        current_session_id=current,
        config=cfg,
    )
    assert len(result) == 1
    assert result[0].session_id == signal
    assert result[0].title == "[signal] aetheria +19102489392"
    assert result[0].paired_turns == (
        PairedTurn(user="from signal", assistant="ack"),
    )


def test_session_with_only_orphan_assistant_is_skipped(tmp_path):
    """Assistant-only session yields no pairs, so no SessionTail emitted."""
    store = ConversationStore(tmp_path / "conv.db")
    current = store.new_session("aetheria")
    other = store.new_session("aetheria")
    store.save_turn(other, "aetheria", "assistant", "unsolicited opener")
    cfg = ContinuityConfig()
    result = recent_cross_session_tails(
        store,
        agent="aetheria",
        current_session_id=current,
        config=cfg,
    )
    assert result == ()


def test_returns_multiple_sessions_in_newest_first_order(tmp_path):
    """Two valid sessions → newest-updated_at first."""
    store = ConversationStore(tmp_path / "conv.db")
    current = store.new_session("aetheria")

    older = store.new_session("aetheria")
    store.save_turn(older, "aetheria", "user", "older u")
    store.save_turn(older, "aetheria", "assistant", "older a")
    time.sleep(0.01)
    newer = store.new_session("aetheria")
    store.save_turn(newer, "aetheria", "user", "newer u")
    store.save_turn(newer, "aetheria", "assistant", "newer a")

    cfg = ContinuityConfig()
    result = recent_cross_session_tails(
        store,
        agent="aetheria",
        current_session_id=current,
        config=cfg,
    )
    assert [t.session_id for t in result] == [newer, older]
    # Sanity: both are SessionTail with paired turns populated
    assert all(isinstance(t, SessionTail) for t in result)
    assert all(t.paired_turns for t in result)
