"""Tests for the once-per-day, morning-only X-post nudge.

The nudge logic is a pure predicate (`should_nudge`) — clock injected, no
I/O — plus tiny best-effort JSON state read/write helpers.
"""

from __future__ import annotations

from datetime import datetime

from soveryn.agents.heartbeat.daily_post import (
    read_last_invite_date,
    should_nudge,
    write_last_invite_date,
)


# ─── should_nudge (pure) ─────────────────────────────────────────────────────


def test_nudge_fires_when_hour_reached_and_new_day():
    # 08:00, never nudged before -> fire.
    now = datetime(2026, 7, 13, 8, 0)
    assert should_nudge(now=now, last_invite_date=None, hour_threshold=8) is True


def test_no_nudge_before_the_hour():
    now = datetime(2026, 7, 13, 7, 59)
    assert should_nudge(now=now, last_invite_date=None, hour_threshold=8) is False


def test_no_nudge_twice_same_day():
    # Already nudged today -> a later tick the same day must not re-fire.
    now = datetime(2026, 7, 13, 10, 30)
    assert should_nudge(now=now, last_invite_date="2026-07-13", hour_threshold=8) is False


def test_nudge_resumes_next_day():
    now = datetime(2026, 7, 14, 8, 5)
    assert should_nudge(now=now, last_invite_date="2026-07-13", hour_threshold=8) is True


def test_no_nudge_next_day_before_the_hour():
    now = datetime(2026, 7, 14, 6, 0)
    assert should_nudge(now=now, last_invite_date="2026-07-13", hour_threshold=8) is False


def test_exactly_at_threshold_hour_fires():
    now = datetime(2026, 7, 13, 8, 0)
    assert should_nudge(now=now, last_invite_date="2026-07-12", hour_threshold=8) is True


# ─── state file (best-effort I/O) ────────────────────────────────────────────


def test_read_missing_state_is_none(tmp_path):
    assert read_last_invite_date(tmp_path / "nope.json") is None


def test_write_then_read_roundtrip(tmp_path):
    p = tmp_path / "state.json"
    write_last_invite_date(p, "2026-07-13")
    assert read_last_invite_date(p) == "2026-07-13"


def test_read_corrupt_state_is_none(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{not json")
    assert read_last_invite_date(p) is None


def test_write_creates_parent_dirs(tmp_path):
    p = tmp_path / "sub" / "dir" / "state.json"
    write_last_invite_date(p, "2026-07-13")
    assert read_last_invite_date(p) == "2026-07-13"


def test_state_roundtrip_drives_should_nudge(tmp_path):
    # End-to-end of the daemon's contract: after writing today's date, a
    # same-day check must NOT re-nudge; the next day it resumes.
    p = tmp_path / "state.json"
    write_last_invite_date(p, "2026-07-13")
    last = read_last_invite_date(p)
    assert should_nudge(now=datetime(2026, 7, 13, 12, 0), last_invite_date=last, hour_threshold=8) is False
    assert should_nudge(now=datetime(2026, 7, 14, 8, 0), last_invite_date=last, hour_threshold=8) is True
