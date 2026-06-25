"""Tests for soveryn.agents.cognition.cycle — run_deep_cycle().

TDD: tests written FIRST, before cycle.py exists.

Spec: docs/superpowers/specs/2026-06-22-continuous-cognition-design.md
      Phase 2, Task 2.4 — deep cognition cycle orchestration.

This module tests the orchestration seam: reflect → gate/process → distill.
It does NOT test scheduling, timers, or the real-time tier (those are separate
tasks).

Test matrix:
  1. full cycle — manner+cited+jon_originated candidate + note returned →
       CycleResult(candidate_count=1, process.integrated has 1, note written,
       store.current_note() returns it)
  2. value-only candidate → process.surfaced has 1, integrated empty;
       note is None if store had no prior reflections (distill not called on empty)
  3. empty turns → candidate_count 0, integrated empty, note None
       (reflect short-circuits; distill not called)
  4. prior note is passed into reflect_chat_fn — capture the system prompt to
       assert the current note text appears in it
  5. second cycle supersedes the first — store.current_note() returns second note
"""

import json

import pytest

from soveryn.platform.lattice.legacy import LatticeStore
from soveryn.agents.cognition.store import CognitionStore
from soveryn.agents.cognition.types import Turn
from soveryn.agents.cognition.cycle import CycleResult, run_deep_cycle


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def lattice_path(tmp_path):
    """Fresh lattice DB with full schema initialized."""
    db_path = tmp_path / "test_cycle.db"
    LatticeStore(db_path)   # init schema — same pattern as other cognition tests
    return db_path


@pytest.fixture
def store(lattice_path):
    return CognitionStore(lattice_path)


# ─── Fake chat_fn builders ────────────────────────────────────────────────────

def _reflect_fn_returning(observations: list[dict]):
    """Returns a reflect_chat_fn that emits a fixed JSON array."""
    payload = json.dumps(observations)
    def fn(system: str, user: str) -> str:
        return payload
    return fn


def _reflect_fn_capturing(observations: list[dict], captured: list):
    """Captures the (system, user) args in `captured`, then returns payload."""
    payload = json.dumps(observations)
    def fn(system: str, user: str) -> str:
        captured.append((system, user))
        return payload
    return fn


def _distill_fn_returning(note_text: str):
    """Returns a distill_chat_fn that emits fixed note text."""
    def fn(system: str, user: str) -> str:
        return note_text
    return fn


def _distill_fn_never_called():
    """distill_chat_fn that fails if called — used to assert distill is skipped."""
    def fn(system: str, user: str) -> str:
        raise AssertionError("distill_chat_fn should not have been called")
    return fn


# ─── Shared turn fixtures ─────────────────────────────────────────────────────

TURNS_ONE = [
    Turn(turn_id="t1", role="user", content="skip the hedging please"),
    Turn(turn_id="t2", role="assistant", content="noted, being direct"),
]

MANNER_CANDIDATE = {
    "text": "Jon reads hedging as noise.",
    "scope": "manner",
    "citations": ["t1"],
    "jon_originated": True,
}

VALUE_CANDIDATE = {
    "text": "Jon values autonomy deeply.",
    "scope": "value",
    "citations": ["t1"],
    "jon_originated": True,
}


# ─── 1. Full cycle: manner candidate + note returned ─────────────────────────

def test_full_cycle_candidate_count(store):
    """CycleResult.candidate_count reflects what reflect() returned."""
    result = run_deep_cycle(
        agent="aetheria",
        turns=TURNS_ONE,
        store=store,
        reflect_chat_fn=_reflect_fn_returning([MANNER_CANDIDATE]),
        distill_chat_fn=_distill_fn_returning("Jon reads hedging as noise."),
    )
    assert result.candidate_count == 1


def test_full_cycle_process_integrated_has_one(store):
    result = run_deep_cycle(
        agent="aetheria",
        turns=TURNS_ONE,
        store=store,
        reflect_chat_fn=_reflect_fn_returning([MANNER_CANDIDATE]),
        distill_chat_fn=_distill_fn_returning("Jon reads hedging as noise."),
    )
    assert len(result.process.integrated) == 1


def test_full_cycle_note_is_written(store):
    """NoteVersion must be returned and persisted to the store."""
    expected_note = "Jon reads hedging as noise."
    result = run_deep_cycle(
        agent="aetheria",
        turns=TURNS_ONE,
        store=store,
        reflect_chat_fn=_reflect_fn_returning([MANNER_CANDIDATE]),
        distill_chat_fn=_distill_fn_returning(expected_note),
    )
    assert result.note is not None
    assert store.current_note() == expected_note


def test_full_cycle_result_is_cycle_result(store):
    result = run_deep_cycle(
        agent="aetheria",
        turns=TURNS_ONE,
        store=store,
        reflect_chat_fn=_reflect_fn_returning([MANNER_CANDIDATE]),
        distill_chat_fn=_distill_fn_returning("Jon reads hedging as noise."),
    )
    assert isinstance(result, CycleResult)


def test_full_cycle_result_is_frozen(store):
    """CycleResult must be immutable (frozen dataclass)."""
    result = run_deep_cycle(
        agent="aetheria",
        turns=TURNS_ONE,
        store=store,
        reflect_chat_fn=_reflect_fn_returning([MANNER_CANDIDATE]),
        distill_chat_fn=_distill_fn_returning("note"),
    )
    with pytest.raises((AttributeError, TypeError)):
        result.candidate_count = 99  # type: ignore[misc]


# ─── 2. Value-only candidate → surfaced, not integrated; note None ───────────

def test_value_only_candidate_surfaced(store):
    result = run_deep_cycle(
        agent="aetheria",
        turns=TURNS_ONE,
        store=store,
        reflect_chat_fn=_reflect_fn_returning([VALUE_CANDIDATE]),
        distill_chat_fn=_distill_fn_never_called(),
    )
    assert len(result.process.surfaced) == 1


def test_value_only_candidate_not_integrated(store):
    result = run_deep_cycle(
        agent="aetheria",
        turns=TURNS_ONE,
        store=store,
        reflect_chat_fn=_reflect_fn_returning([VALUE_CANDIDATE]),
        distill_chat_fn=_distill_fn_never_called(),
    )
    assert len(result.process.integrated) == 0


def test_value_only_note_is_none_when_store_empty(store):
    """With no integrated reflections in the store, distill is never called."""
    result = run_deep_cycle(
        agent="aetheria",
        turns=TURNS_ONE,
        store=store,
        reflect_chat_fn=_reflect_fn_returning([VALUE_CANDIDATE]),
        distill_chat_fn=_distill_fn_never_called(),
    )
    assert result.note is None


def test_value_only_candidate_count(store):
    result = run_deep_cycle(
        agent="aetheria",
        turns=TURNS_ONE,
        store=store,
        reflect_chat_fn=_reflect_fn_returning([VALUE_CANDIDATE]),
        distill_chat_fn=_distill_fn_never_called(),
    )
    assert result.candidate_count == 1


# ─── 3. Empty turns → candidate_count 0, note None ──────────────────────────

def test_empty_turns_candidate_count_zero(store):
    result = run_deep_cycle(
        agent="aetheria",
        turns=[],
        store=store,
        reflect_chat_fn=_reflect_fn_returning([]),   # should not be called
        distill_chat_fn=_distill_fn_never_called(),
    )
    assert result.candidate_count == 0


def test_empty_turns_integrated_empty(store):
    result = run_deep_cycle(
        agent="aetheria",
        turns=[],
        store=store,
        reflect_chat_fn=_reflect_fn_returning([]),
        distill_chat_fn=_distill_fn_never_called(),
    )
    assert len(result.process.integrated) == 0


def test_empty_turns_note_is_none(store):
    result = run_deep_cycle(
        agent="aetheria",
        turns=[],
        store=store,
        reflect_chat_fn=_reflect_fn_returning([]),
        distill_chat_fn=_distill_fn_never_called(),
    )
    assert result.note is None


# ─── 4. Prior note passed into reflect_chat_fn ───────────────────────────────

def test_prior_note_appears_in_reflect_system_prompt(store):
    """The current note text must be visible in the system prompt sent to reflect_chat_fn.

    Mechanism: run_deep_cycle reads store.current_note() and passes it as
    prior_note to reflect().  reflect() bakes it into the system prompt.
    We write a note directly to the store first, then run a cycle and
    capture the system prompt.
    """
    # Seed the store with a known note
    prior_text = "Prior note: Jon values concision."
    store.write_note_version(prior_text)

    captured: list = []
    result = run_deep_cycle(
        agent="aetheria",
        turns=TURNS_ONE,
        store=store,
        reflect_chat_fn=_reflect_fn_capturing([MANNER_CANDIDATE], captured),
        distill_chat_fn=_distill_fn_returning("updated note"),
    )

    assert len(captured) == 1, "reflect_chat_fn should have been called exactly once"
    system_prompt, _user_prompt = captured[0]
    assert prior_text in system_prompt, (
        f"Prior note text not found in reflect system prompt.\n"
        f"Expected to find: {prior_text!r}\n"
        f"System prompt was: {system_prompt[:500]!r}"
    )


# ─── 5. Second cycle supersedes first ────────────────────────────────────────

def test_second_cycle_supersedes_first(store):
    """A second run_deep_cycle must overwrite the note from the first.

    store.current_note() returns the latest version; the first note
    must not survive as the current note.
    """
    first_note = "First cycle note: Jon dislikes hedging."
    second_note = "Second cycle note: Jon also dislikes padding."

    # First cycle
    run_deep_cycle(
        agent="aetheria",
        turns=TURNS_ONE,
        store=store,
        reflect_chat_fn=_reflect_fn_returning([MANNER_CANDIDATE]),
        distill_chat_fn=_distill_fn_returning(first_note),
    )

    # Second cycle with different candidates to produce new reflections
    second_candidate = {
        "text": "Jon also dislikes padding.",
        "scope": "manner",
        "citations": ["t2"],
        "jon_originated": True,
    }
    run_deep_cycle(
        agent="aetheria",
        turns=TURNS_ONE,
        store=store,
        reflect_chat_fn=_reflect_fn_returning([second_candidate]),
        distill_chat_fn=_distill_fn_returning(second_note),
    )

    current = store.current_note()
    assert current == second_note, (
        f"Expected second cycle note {second_note!r} to be current, got {current!r}"
    )
    # First note must no longer be current (though it remains in history)
    assert current != first_note
