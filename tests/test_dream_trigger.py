"""Tests for soveryn.agents.dream.trigger — eligibility gates as pure functions.

Five gates per spec, evaluated in order: disabled > outside_quiet_hours >
already_dreamed_this_window > activity_backoff > nothing_to_dream_about.
"""

from datetime import datetime, time, timedelta

import pytest

from soveryn.agents.dream.config import DreamConfig
from soveryn.agents.dream.trigger import (
    DreamSkipReason,
    TickEligibility,
    evaluate_tick,
    in_quiet_window,
)


def _cfg(**kw) -> DreamConfig:
    base = dict(
        enabled=True, dry_run=True, quiet_hours="23:00-07:00",
        activity_backoff_seconds=1800, nodes_per_run=300,
        max_internal_iterations=3,
        cognition_url="http://x", cognition_timeout_seconds=120,
    )
    base.update(kw)
    return DreamConfig(**base)


# Inside-window probe time: 02:00. Outside-window probe: 14:00.
NIGHT = datetime(2026, 6, 5, 2, 0, 0)
DAY = datetime(2026, 6, 5, 14, 0, 0)


# ─── in_quiet_window helper ─────────────────────────────────────────────────

def test_in_quiet_window_simple_window():
    assert in_quiet_window(time(3, 0), "01:00-05:00") is True
    assert in_quiet_window(time(0, 0), "01:00-05:00") is False
    assert in_quiet_window(time(5, 0), "01:00-05:00") is False


def test_in_quiet_window_wrap_around():
    """23:00-07:00 covers 23:00 through 06:59:59 across midnight."""
    assert in_quiet_window(time(23, 30), "23:00-07:00") is True
    assert in_quiet_window(time(2, 0), "23:00-07:00") is True
    assert in_quiet_window(time(7, 0), "23:00-07:00") is False
    assert in_quiet_window(time(22, 0), "23:00-07:00") is False


def test_in_quiet_window_malformed_returns_false():
    assert in_quiet_window(time(3, 0), "garbage") is False
    assert in_quiet_window(time(3, 0), "") is False


# ─── evaluate_tick gates ────────────────────────────────────────────────────

def test_disabled_short_circuits():
    e = evaluate_tick(_cfg(enabled=False), now=NIGHT,
                       last_dream_at=None, last_activity_at=None,
                       new_node_count_since_last_dream=10)
    assert e.eligible is False
    assert e.skip_reason == DreamSkipReason.DISABLED


def test_outside_quiet_hours():
    e = evaluate_tick(_cfg(), now=DAY,
                       last_dream_at=None, last_activity_at=None,
                       new_node_count_since_last_dream=10)
    assert e.eligible is False
    assert e.skip_reason == DreamSkipReason.OUTSIDE_QUIET_HOURS


def test_already_dreamed_this_window():
    """A successful dream at 23:30 last night blocks a 02:00 run tonight."""
    last_dream = NIGHT - timedelta(hours=2, minutes=30)  # 23:30 same window
    e = evaluate_tick(_cfg(), now=NIGHT,
                       last_dream_at=last_dream,
                       last_activity_at=None,
                       new_node_count_since_last_dream=10)
    assert e.eligible is False
    assert e.skip_reason == DreamSkipReason.ALREADY_DREAMED


def test_already_dreamed_24h_ago_does_not_block():
    """Last night's dream shouldn't block tonight's."""
    last_dream = NIGHT - timedelta(hours=25)
    e = evaluate_tick(_cfg(), now=NIGHT,
                       last_dream_at=last_dream,
                       last_activity_at=None,
                       new_node_count_since_last_dream=10)
    assert e.eligible is True


def test_activity_backoff_blocks_when_aetheria_was_active():
    """Aetheria activity within backoff window defers the dream."""
    last_activity = NIGHT - timedelta(minutes=10)  # 10 min ago, well within 30 min
    e = evaluate_tick(_cfg(), now=NIGHT,
                       last_dream_at=None,
                       last_activity_at=last_activity,
                       new_node_count_since_last_dream=10)
    assert e.eligible is False
    assert e.skip_reason == DreamSkipReason.ACTIVITY_BACKOFF


def test_nothing_to_dream_about():
    """Zero new nodes since last dream → skip."""
    e = evaluate_tick(_cfg(), now=NIGHT,
                       last_dream_at=NIGHT - timedelta(hours=25),
                       last_activity_at=None,
                       new_node_count_since_last_dream=0)
    assert e.eligible is False
    assert e.skip_reason == DreamSkipReason.NOTHING_TO_DREAM_ABOUT


def test_eligible_when_all_gates_pass():
    e = evaluate_tick(_cfg(), now=NIGHT,
                       last_dream_at=NIGHT - timedelta(hours=25),
                       last_activity_at=NIGHT - timedelta(hours=2),
                       new_node_count_since_last_dream=12)
    assert e.eligible is True
    assert e.skip_reason is None


def test_disabled_wins_over_other_failures():
    """Order matters: disabled checked before any other gate."""
    e = evaluate_tick(_cfg(enabled=False), now=DAY,
                       last_dream_at=None, last_activity_at=None,
                       new_node_count_since_last_dream=0)
    assert e.skip_reason == DreamSkipReason.DISABLED
