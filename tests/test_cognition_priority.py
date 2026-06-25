"""Tests for soveryn.agents.cognition.priority — priority_trigger().

TDD: tests written FIRST, before priority.py exists.

Spec: docs/superpowers/specs/2026-06-22-continuous-cognition-design.md
      Phase 2, Task 2.5 — priority trigger.

## What this module tests

`priority_trigger()` is the high-salience fast path: reflect → surface.
It is a SURFACE-ONLY operation.  The load-bearing contract:

  - Returns candidates from reflect() as the surface payload for Jon.
  - NEVER writes to the store (no write_reflection, no write_note_version).
  - The baseline (sense-of-us note) is UNTOUCHED after a priority trigger.
  - The current note IS passed as prior_note into reflect (no blank context).
  - Empty turns → [] without calling reflect_chat_fn.

Test matrix:
  1. high-salience turn → reflect returns observations → priority_trigger returns them.
  2. STORE IS UNTOUCHED: after priority_trigger, store.list_reflections() == []
       AND store.current_note() is unchanged (the seeded note survives verbatim).
       This is the load-bearing test — proves no baseline rewrite.
  3. The current note is passed as prior_note into reflect (captured in system prompt).
  4. Empty turns → [].
"""

import json

import pytest

from soveryn.platform.lattice.legacy import LatticeStore
from soveryn.agents.cognition.store import CognitionStore
from soveryn.agents.cognition.types import CandidateObservation, Turn
from soveryn.agents.cognition.priority import priority_trigger


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def lattice_path(tmp_path):
    """Fresh lattice DB with full schema initialized."""
    db_path = tmp_path / "test_priority.db"
    LatticeStore(db_path)   # init schema — same pattern as other cognition tests
    return db_path


@pytest.fixture
def store(lattice_path):
    return CognitionStore(lattice_path)


# ─── Fake reflect_chat_fn builders ───────────────────────────────────────────

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


def _reflect_fn_never_called():
    """reflect_chat_fn that fails if called — used to assert reflect is skipped."""
    def fn(system: str, user: str) -> str:
        raise AssertionError("reflect_chat_fn should not have been called")
    return fn


# ─── Shared data ─────────────────────────────────────────────────────────────

TURNS_ONE = [
    Turn(turn_id="t1", role="user", content="drop the filler, just the answer"),
    Turn(turn_id="t2", role="assistant", content="understood, being direct"),
]

MANNER_CANDIDATE = {
    "text": "Jon wants answers without filler.",
    "scope": "manner",
    "citations": ["t1"],
    "jon_originated": True,
}

VALUE_CANDIDATE = {
    "text": "Jon values self-direction deeply.",
    "scope": "value",
    "citations": ["t1"],
    "jon_originated": True,
}

SEEDED_NOTE = "Prior sense-of-us: Jon reads hedging as noise."


# ─── 1. Returns reflect() observations as the surface payload ────────────────

def test_priority_trigger_returns_candidates(store):
    """priority_trigger returns whatever reflect() emits — the surface payload."""
    result = priority_trigger(
        agent="aetheria",
        turns=TURNS_ONE,
        store=store,
        reflect_chat_fn=_reflect_fn_returning([MANNER_CANDIDATE]),
    )
    assert len(result) == 1


def test_priority_trigger_returns_candidate_observation_type(store):
    """Each returned item is a CandidateObservation."""
    result = priority_trigger(
        agent="aetheria",
        turns=TURNS_ONE,
        store=store,
        reflect_chat_fn=_reflect_fn_returning([MANNER_CANDIDATE]),
    )
    assert all(isinstance(obs, CandidateObservation) for obs in result)


def test_priority_trigger_preserves_candidate_text(store):
    """The text of the returned observation matches what reflect emitted."""
    result = priority_trigger(
        agent="aetheria",
        turns=TURNS_ONE,
        store=store,
        reflect_chat_fn=_reflect_fn_returning([MANNER_CANDIDATE]),
    )
    assert result[0].text == MANNER_CANDIDATE["text"]


def test_priority_trigger_multiple_candidates_returned(store):
    """priority_trigger surfaces all candidates reflect() returns."""
    candidates = [MANNER_CANDIDATE, VALUE_CANDIDATE]
    result = priority_trigger(
        agent="aetheria",
        turns=TURNS_ONE,
        store=store,
        reflect_chat_fn=_reflect_fn_returning(candidates),
    )
    assert len(result) == 2


# ─── 2. LOAD-BEARING: store is completely untouched after priority_trigger ───

def test_priority_trigger_no_reflections_written(store):
    """priority_trigger MUST NOT write any reflections to the store.

    This is the load-bearing guard: high-salience events surface immediately
    but never integrate — baseline rewrite is the normal deep cycle's job.
    """
    priority_trigger(
        agent="aetheria",
        turns=TURNS_ONE,
        store=store,
        reflect_chat_fn=_reflect_fn_returning([MANNER_CANDIDATE]),
    )
    assert store.list_reflections() == []


def test_priority_trigger_seeded_note_survives_verbatim(store):
    """priority_trigger MUST NOT touch the sense-of-us note.

    Seed a note, run a priority trigger, assert the exact same note text
    is still the current note.  Any write would change it.
    """
    store.write_note_version(SEEDED_NOTE)

    priority_trigger(
        agent="aetheria",
        turns=TURNS_ONE,
        store=store,
        reflect_chat_fn=_reflect_fn_returning([MANNER_CANDIDATE]),
    )

    assert store.current_note() == SEEDED_NOTE


def test_priority_trigger_note_stays_none_when_store_empty(store):
    """If no note was ever written, current_note() must still be None after."""
    assert store.current_note() is None  # precondition

    priority_trigger(
        agent="aetheria",
        turns=TURNS_ONE,
        store=store,
        reflect_chat_fn=_reflect_fn_returning([MANNER_CANDIDATE]),
    )

    assert store.current_note() is None


def test_priority_trigger_no_store_writes_value_candidate(store):
    """Even value-scope candidates must not be persisted to the store."""
    store.write_note_version(SEEDED_NOTE)

    priority_trigger(
        agent="aetheria",
        turns=TURNS_ONE,
        store=store,
        reflect_chat_fn=_reflect_fn_returning([VALUE_CANDIDATE]),
    )

    assert store.list_reflections() == []
    assert store.current_note() == SEEDED_NOTE


# ─── 3. Current note is passed as prior_note into reflect ────────────────────

def test_priority_trigger_passes_current_note_to_reflect(store):
    """The seeded note text must appear in the system prompt sent to reflect_chat_fn.

    Mechanism: priority_trigger reads store.current_note() and passes it as
    prior_note to reflect().  reflect() bakes it into the system prompt.
    """
    store.write_note_version(SEEDED_NOTE)

    captured: list = []
    priority_trigger(
        agent="aetheria",
        turns=TURNS_ONE,
        store=store,
        reflect_chat_fn=_reflect_fn_capturing([MANNER_CANDIDATE], captured),
    )

    assert len(captured) == 1, "reflect_chat_fn should have been called exactly once"
    system_prompt, _user_prompt = captured[0]
    assert SEEDED_NOTE in system_prompt, (
        f"Current note text not found in reflect system prompt.\n"
        f"Expected to find: {SEEDED_NOTE!r}\n"
        f"System prompt was: {system_prompt[:500]!r}"
    )


def test_priority_trigger_passes_empty_string_when_no_note(store):
    """When no note exists, reflect must still be called (with empty prior)."""
    captured: list = []
    priority_trigger(
        agent="aetheria",
        turns=TURNS_ONE,
        store=store,
        reflect_chat_fn=_reflect_fn_capturing([MANNER_CANDIDATE], captured),
    )

    assert len(captured) == 1, "reflect_chat_fn should have been called once even with no note"


# ─── 4. Empty turns → [] ────────────────────────────────────────────────────

def test_priority_trigger_empty_turns_returns_empty_list(store):
    """Empty turns short-circuit immediately — no reflect_chat_fn call."""
    result = priority_trigger(
        agent="aetheria",
        turns=[],
        store=store,
        reflect_chat_fn=_reflect_fn_never_called(),
    )
    assert result == []


def test_priority_trigger_empty_turns_no_store_writes(store):
    """Empty turns must not write anything to the store either."""
    store.write_note_version(SEEDED_NOTE)

    priority_trigger(
        agent="aetheria",
        turns=[],
        store=store,
        reflect_chat_fn=_reflect_fn_never_called(),
    )

    assert store.list_reflections() == []
    assert store.current_note() == SEEDED_NOTE
