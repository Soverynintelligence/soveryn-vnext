"""Tests for soveryn.agents.cognition.daemon — CognitionDaemon.

TDD: tests written FIRST, before daemon.py exists.

Spec: docs/superpowers/specs/2026-06-22-continuous-cognition-design.md
      Phase 2, Task 2.4b — deep-tier cognition daemon (scheduler).

The daemon wraps run_deep_cycle() with a quiet-time / idle gate so the
cycle only fires when the system is idle.  This test module covers:

  1. should_run_deep — false when not idle long enough
  2. should_run_deep — false when idle but too soon since last cycle
  3. should_run_deep — true when both conditions met
  4. maybe_run_deep_cycle runs and returns CycleResult when quiet-time holds
  5. maybe_run_deep_cycle updates last_cycle_at so immediate re-call returns None
  6. maybe_run_deep_cycle returns None and does NOT call the model when not idle
  7. after a real run the cognition store reflects the cycle's effects
     (reflection + note written to a tmp store via fakes that produce one
     manner candidate + a note)

Design: all external dependencies injected so the test never touches a real
clock, a real model, or a real conversation source.
"""

from __future__ import annotations

import json

import pytest

from soveryn.platform.lattice.legacy import LatticeStore
from soveryn.agents.cognition.store import CognitionStore
from soveryn.agents.cognition.types import Turn
from soveryn.agents.cognition.daemon import CognitionDaemon, CognitionDaemonConfig


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def lattice_path(tmp_path):
    db = tmp_path / "test_daemon.db"
    LatticeStore(db)
    return db


@pytest.fixture
def store(lattice_path):
    return CognitionStore(lattice_path)


# ─── Fake chat_fn builders ────────────────────────────────────────────────────

MANNER_CANDIDATE = {
    "text": "Jon prefers concise responses.",
    "scope": "manner",
    "citations": ["t1"],
    "jon_originated": True,
}

CALL_LOG: list[str] = []  # module-level sentinel; cleared per test


def _reflect_fn_returning(observations: list[dict], call_log: list | None = None):
    payload = json.dumps(observations)
    def fn(system: str, user: str) -> str:
        if call_log is not None:
            call_log.append("reflect")
        return payload
    return fn


def _distill_fn_returning(note_text: str, call_log: list | None = None):
    def fn(system: str, user: str) -> str:
        if call_log is not None:
            call_log.append("distill")
        return note_text
    return fn


def _never_called_fn(label: str):
    """chat_fn that fails if invoked — used to assert model not called."""
    def fn(system: str, user: str) -> str:
        raise AssertionError(f"{label} should not have been called")
    return fn


# ─── Shared turn list ─────────────────────────────────────────────────────────

TURNS_ONE = [
    Turn(turn_id="t1", role="user", content="be concise"),
    Turn(turn_id="t2", role="assistant", content="understood"),
]


# ─── Daemon builder helpers ───────────────────────────────────────────────────

def _make_daemon(
    store: CognitionStore,
    *,
    tick_interval: float = 600.0,
    idle_threshold: float = 300.0,
    now_fn,
    last_activity_fn,
    recent_turns_fn=None,
    reflect_chat_fn=None,
    distill_chat_fn=None,
) -> CognitionDaemon:
    config = CognitionDaemonConfig(
        tick_interval_seconds=tick_interval,
        idle_threshold_seconds=idle_threshold,
        agent="aetheria",
    )
    return CognitionDaemon(
        config=config,
        store=store,
        now_fn=now_fn,
        last_activity_fn=last_activity_fn,
        recent_turns_fn=recent_turns_fn or (lambda: []),
        reflect_chat_fn=reflect_chat_fn or _never_called_fn("reflect_chat_fn"),
        distill_chat_fn=distill_chat_fn or _never_called_fn("distill_chat_fn"),
    )


# ─── 1. should_run_deep: false when not idle long enough ─────────────────────

def test_should_run_deep_false_when_not_idle(store):
    """Return False when (now − last_activity) < idle_threshold."""
    # t=1000, last_activity=950 → idle for 50s, threshold=300 → not idle
    daemon = _make_daemon(
        store,
        tick_interval=600.0,
        idle_threshold=300.0,
        now_fn=lambda: 1000.0,
        last_activity_fn=lambda: 950.0,
    )
    assert daemon.should_run_deep(1000.0) is False


# ─── 2. should_run_deep: false when idle but too soon since last cycle ────────

def test_should_run_deep_false_when_too_soon_after_last_cycle(store):
    """Return False when idle ≥ threshold but (now − last_cycle_at) < tick_interval."""
    daemon = _make_daemon(
        store,
        tick_interval=600.0,
        idle_threshold=300.0,
        now_fn=lambda: 2000.0,
        last_activity_fn=lambda: 1500.0,  # idle 500s ≥ 300s threshold
    )
    # Manually set last_cycle_at to simulate a recent cycle 100s ago
    daemon._last_cycle_at = 1900.0
    # now - last_cycle_at = 100 < tick_interval=600 → should NOT run
    assert daemon.should_run_deep(2000.0) is False


# ─── 3. should_run_deep: true when both conditions met ───────────────────────

def test_should_run_deep_true_when_both_conditions_met(store):
    """Return True when idle ≥ threshold AND enough time since last cycle."""
    daemon = _make_daemon(
        store,
        tick_interval=600.0,
        idle_threshold=300.0,
        now_fn=lambda: 3000.0,
        last_activity_fn=lambda: 2500.0,  # idle 500s ≥ 300s threshold
    )
    # last_cycle_at = 2000 → 3000 - 2000 = 1000 ≥ 600 tick_interval → should run
    daemon._last_cycle_at = 2000.0
    assert daemon.should_run_deep(3000.0) is True


def test_should_run_deep_true_when_never_run(store):
    """First run: _last_cycle_at is None → only idle check applies."""
    daemon = _make_daemon(
        store,
        tick_interval=600.0,
        idle_threshold=300.0,
        now_fn=lambda: 1000.0,
        last_activity_fn=lambda: 600.0,  # idle 400s ≥ 300s threshold
    )
    # _last_cycle_at defaults to None → tick_interval gate is bypassed
    assert daemon._last_cycle_at is None
    assert daemon.should_run_deep(1000.0) is True


def test_should_run_deep_false_exactly_at_boundary(store):
    """Exactly at idle_threshold boundary — strictly-less-than means not idle yet
    at equality (implementation may be >=; test documents boundary behaviour)."""
    daemon = _make_daemon(
        store,
        tick_interval=600.0,
        idle_threshold=300.0,
        now_fn=lambda: 1300.0,
        last_activity_fn=lambda: 1000.0,   # idle exactly 300s
    )
    # With >= the daemon IS eligible at exactly the threshold.
    # With > it is not. We test >= (inclusive) as the contract.
    daemon._last_cycle_at = None
    result = daemon.should_run_deep(1300.0)
    # Document the contract: must be True (>= threshold, not strictly >)
    assert result is True


# ─── 4. maybe_run_deep_cycle: runs and returns CycleResult when quiet ─────────

def test_maybe_run_deep_cycle_returns_cycle_result_when_idle(store):
    """When conditions are met, maybe_run_deep_cycle returns a CycleResult."""
    from soveryn.agents.cognition.cycle import CycleResult

    daemon = _make_daemon(
        store,
        tick_interval=600.0,
        idle_threshold=300.0,
        now_fn=lambda: 3000.0,
        last_activity_fn=lambda: 2000.0,  # idle 1000s ≥ 300s
        recent_turns_fn=lambda: TURNS_ONE,
        reflect_chat_fn=_reflect_fn_returning([MANNER_CANDIDATE]),
        distill_chat_fn=_distill_fn_returning("Jon prefers concise responses."),
    )
    daemon._last_cycle_at = None  # never run before

    result = daemon.maybe_run_deep_cycle()

    assert result is not None
    assert isinstance(result, CycleResult)


# ─── 5. maybe_run_deep_cycle updates last_cycle_at so re-call returns None ────

def test_maybe_run_deep_cycle_blocks_immediate_rerun(store):
    """After a successful cycle, _last_cycle_at advances so a second
    immediate call returns None (tick_interval gate blocks it)."""
    now_val = [3000.0]

    def now_fn():
        return now_val[0]

    daemon = _make_daemon(
        store,
        tick_interval=600.0,
        idle_threshold=300.0,
        now_fn=now_fn,
        last_activity_fn=lambda: 2000.0,  # idle 1000s ≥ 300s
        recent_turns_fn=lambda: TURNS_ONE,
        reflect_chat_fn=_reflect_fn_returning([MANNER_CANDIDATE]),
        distill_chat_fn=_distill_fn_returning("note text"),
    )
    daemon._last_cycle_at = None

    # First call — should run
    first = daemon.maybe_run_deep_cycle()
    assert first is not None

    # Second call at same clock — should be blocked by tick_interval gate
    second = daemon.maybe_run_deep_cycle()
    assert second is None


# ─── 6. maybe_run_deep_cycle returns None and does NOT call model when busy ────

def test_maybe_run_deep_cycle_returns_none_when_not_idle(store):
    """When not idle, returns None and never invokes reflect/distill."""
    call_log: list[str] = []

    daemon = _make_daemon(
        store,
        tick_interval=600.0,
        idle_threshold=300.0,
        now_fn=lambda: 1100.0,
        last_activity_fn=lambda: 1000.0,  # idle only 100s < 300s threshold
        recent_turns_fn=lambda: TURNS_ONE,
        reflect_chat_fn=_reflect_fn_returning([MANNER_CANDIDATE], call_log),
        distill_chat_fn=_distill_fn_returning("note", call_log),
    )

    result = daemon.maybe_run_deep_cycle()

    assert result is None
    assert call_log == [], "model fns must not be called when daemon is not idle"


# ─── 7. store reflects cycle effects after a real run ─────────────────────────

def test_store_reflects_cycle_effects_after_run(store):
    """After maybe_run_deep_cycle completes, the CognitionStore holds
    the reflection + note written by the cycle's model calls.

    Uses tmp store + fakes that produce one manner candidate + a note.
    Asserts:
      - store.list_reflections() has exactly one entry with the right text
      - store.current_note() equals the note text from distill_chat_fn
    """
    expected_reflection_text = "Jon prefers concise responses."
    expected_note = "Jon values brevity."

    daemon = _make_daemon(
        store,
        tick_interval=600.0,
        idle_threshold=300.0,
        now_fn=lambda: 5000.0,
        last_activity_fn=lambda: 4000.0,  # idle 1000s ≥ 300s
        recent_turns_fn=lambda: TURNS_ONE,
        reflect_chat_fn=_reflect_fn_returning([MANNER_CANDIDATE]),
        distill_chat_fn=_distill_fn_returning(expected_note),
    )
    daemon._last_cycle_at = None

    result = daemon.maybe_run_deep_cycle()

    assert result is not None

    # Reflection was written
    reflections = store.list_reflections()
    assert len(reflections) == 1
    assert reflections[0].text == expected_reflection_text

    # Note was written
    assert store.current_note() == expected_note
