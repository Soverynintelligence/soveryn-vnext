"""Tests for StagedStore: one staged post per AGENT (not per session), TTL, state.

Keyed on `agent`, not `session_id`, because Aetheria may propose a post during
a heartbeat wake (one session) but Jon approves it from his primary chat
thread (a different session) — session-keying would never match.
"""

from __future__ import annotations

import pytest

from soveryn.agents.presence.staged_store import StagedBusyError, StagedPost, StagedStore


def test_stage_then_pending_returns_it(tmp_path):
    s = StagedStore(tmp_path / "staged.db")
    staged = s.stage(agent="aetheria", text="hello world", reply_to=None, now="2026-07-11T10:00:00")
    assert isinstance(staged, StagedPost)
    assert staged.agent == "aetheria"
    assert staged.text == "hello world"
    assert staged.reply_to is None
    assert staged.proposed_at == "2026-07-11T10:00:00"
    assert staged.state == "proposed"

    pending = s.pending("aetheria")
    assert pending == staged


def test_second_stage_while_proposed_raises_busy(tmp_path):
    s = StagedStore(tmp_path / "staged.db")
    s.stage(agent="aetheria", text="first", reply_to=None, now="2026-07-11T10:00:00")
    with pytest.raises(StagedBusyError):
        s.stage(agent="aetheria", text="second", reply_to=None, now="2026-07-11T10:01:00")


def test_mark_published_clears_pending_and_allows_new_stage(tmp_path):
    s = StagedStore(tmp_path / "staged.db")
    staged = s.stage(agent="aetheria", text="first", reply_to=None, now="2026-07-11T10:00:00")
    s.mark(staged.id, "published")

    assert s.pending("aetheria") is None

    second = s.stage(agent="aetheria", text="second", reply_to=None, now="2026-07-11T10:05:00")
    assert s.pending("aetheria") == second


def test_mark_rejected_clears_pending(tmp_path):
    s = StagedStore(tmp_path / "staged.db")
    staged = s.stage(agent="aetheria", text="first", reply_to=None, now="2026-07-11T10:00:00")
    s.mark(staged.id, "rejected")
    assert s.pending("aetheria") is None


def test_pending_none_when_nothing_staged(tmp_path):
    s = StagedStore(tmp_path / "staged.db")
    assert s.pending("aetheria") is None


def test_pending_is_agent_scoped(tmp_path):
    s = StagedStore(tmp_path / "staged.db")
    s.stage(agent="aetheria", text="aetheria post", reply_to=None, now="2026-07-11T10:00:00")
    assert s.pending("vett") is None
    assert s.pending("aetheria") is not None


def test_expire_stale_flips_only_old_proposed_leaves_fresh(tmp_path):
    s = StagedStore(tmp_path / "staged.db")
    old = s.stage(agent="aetheria", text="old one", reply_to=None, now="2026-07-11T00:00:00")

    expired = s.expire_stale(now="2026-07-11T10:00:00", ttl_hours=1.0)

    assert len(expired) == 1
    assert expired[0].id == old.id
    assert expired[0].state == "expired"
    assert s.pending("aetheria") is None

    fresh = s.stage(agent="aetheria", text="fresh one", reply_to=None, now="2026-07-11T10:01:00")
    still_pending = s.expire_stale(now="2026-07-11T10:05:00", ttl_hours=1.0)
    assert still_pending == []
    assert s.pending("aetheria") == fresh


def test_stage_id_is_deterministic_not_random(tmp_path):
    s1 = StagedStore(tmp_path / "a.db")
    s2 = StagedStore(tmp_path / "b.db")
    p1 = s1.stage(agent="aetheria", text="same text", reply_to=None, now="2026-07-11T10:00:00")
    p2 = s2.stage(agent="aetheria", text="same text", reply_to=None, now="2026-07-11T10:00:00")
    assert p1.id == p2.id


def test_reply_to_round_trips(tmp_path):
    s = StagedStore(tmp_path / "staged.db")
    staged = s.stage(agent="aetheria", text="a reply", reply_to="tweet-123", now="2026-07-11T10:00:00")
    assert staged.reply_to == "tweet-123"
    assert s.pending("aetheria").reply_to == "tweet-123"
