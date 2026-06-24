"""Tests for soveryn.agents.cognition.pipeline — process_candidates().

TDD: tests written FIRST, before pipeline.py exists.

Spec: docs/superpowers/specs/2026-06-22-continuous-cognition-design.md
      "The worth-keeping gate" + "Data flow"

Fixture pattern mirrors test_cognition_store.py (LatticeStore init, then
CognitionStore constructed over same path).

Test matrix:
  1. manner + cited + jon_originated → integrated (in result.integrated, persisted)
  2. value + cited + jon_originated → surfaced (in result.surfaced, NOT in store)
  3. uncited (citations=()) → dropped (result.dropped == 1, NOT in store)
  4. not jon_originated (jon_originated=False) → dropped (result.dropped == 1, NOT in store)
  5. mixed batch (one integrate / one surface / one drop) → correct 3-way routing
  6. empty input → empty ProcessResult (0/0/0)
"""

import pytest

from soveryn.platform.lattice.legacy import LatticeStore
from soveryn.agents.cognition.types import CandidateObservation, ReflectionMemory
from soveryn.agents.cognition.store import CognitionStore
from soveryn.agents.cognition.pipeline import ProcessResult, process_candidates


# ─── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def lattice_path(tmp_path):
    """Fresh lattice DB with full schema initialized."""
    db_path = tmp_path / "test_pipeline.db"
    LatticeStore(db_path)  # init schema (idempotent — mirrors coord/cognition tests)
    return db_path


@pytest.fixture
def store(lattice_path):
    return CognitionStore(lattice_path)


# ─── Candidate helpers ───────────────────────────────────────────────────────

def manner_candidate(text: str = "Jon prefers brevity") -> CandidateObservation:
    """manner + cited + jon_originated — should INTEGRATE."""
    return CandidateObservation(
        text=text,
        scope="manner",
        citations=("turn-001",),
        jon_originated=True,
    )


def value_candidate(text: str = "Jon values autonomy") -> CandidateObservation:
    """value + cited + jon_originated — should SURFACE."""
    return CandidateObservation(
        text=text,
        scope="value",
        citations=("turn-002",),
        jon_originated=True,
    )


def uncited_candidate(text: str = "vague vibe, no evidence") -> CandidateObservation:
    """No citations — should DROP."""
    return CandidateObservation(
        text=text,
        scope="manner",
        citations=(),          # empty — gate rule 1 drops this
        jon_originated=True,
    )


def agent_self_originated_candidate(text: str = "agent self-assessed") -> CandidateObservation:
    """jon_originated=False — should DROP (echo-chamber guard)."""
    return CandidateObservation(
        text=text,
        scope="manner",
        citations=("turn-003",),
        jon_originated=False,  # gate rule 2 drops this
    )


# ─── 1. manner + cited + jon_originated → integrated ────────────────────────

def test_manner_candidate_lands_in_integrated(store):
    obs = manner_candidate()
    result = process_candidates([obs], store)
    assert len(result.integrated) == 1
    assert result.integrated[0].text == obs.text


def test_manner_candidate_integrated_is_reflection_memory(store):
    obs = manner_candidate()
    result = process_candidates([obs], store)
    assert isinstance(result.integrated[0], ReflectionMemory)


def test_manner_candidate_is_actually_persisted(store):
    """integrate verdict must call store.write_reflection → row must survive round-trip."""
    obs = manner_candidate("Jon reads hedging as noise")
    process_candidates([obs], store)
    reflections = store.list_reflections()
    assert any(r.text == "Jon reads hedging as noise" for r in reflections)


def test_manner_candidate_persisted_region_is_cognition(store):
    """Persisted row must carry region='cognition' (write-isolation enforced end-to-end)."""
    import json, sqlite3
    obs = manner_candidate("brevity signal")
    result = process_candidates([obs], store)
    mem_id = result.integrated[0].id
    conn = sqlite3.connect(str(store.db_path))
    row = conn.execute("SELECT provenance FROM nodes WHERE id = ?", (mem_id,)).fetchone()
    conn.close()
    prov = json.loads(row[0])
    assert prov["region"] == "cognition"


def test_manner_candidate_not_in_surfaced_or_dropped(store):
    obs = manner_candidate()
    result = process_candidates([obs], store)
    assert len(result.surfaced) == 0
    assert result.dropped == 0


# ─── 2. value + cited + jon_originated → surfaced ───────────────────────────

def test_value_candidate_lands_in_surfaced(store):
    obs = value_candidate()
    result = process_candidates([obs], store)
    assert len(result.surfaced) == 1
    assert result.surfaced[0].text == obs.text


def test_value_candidate_surfaced_is_candidate_observation(store):
    """Surfaced items are the original CandidateObservation — not yet persisted."""
    obs = value_candidate()
    result = process_candidates([obs], store)
    assert isinstance(result.surfaced[0], CandidateObservation)


def test_value_candidate_not_written_to_store(store):
    """value verdict must NOT persist to the lattice."""
    obs = value_candidate("Jon values autonomy — surfaced, not silently applied")
    process_candidates([obs], store)
    reflections = store.list_reflections()
    assert not any(r.text == obs.text for r in reflections)


def test_value_candidate_not_in_integrated_or_dropped(store):
    obs = value_candidate()
    result = process_candidates([obs], store)
    assert len(result.integrated) == 0
    assert result.dropped == 0


# ─── 3. uncited → dropped ────────────────────────────────────────────────────

def test_uncited_candidate_counted_in_dropped(store):
    obs = uncited_candidate()
    result = process_candidates([obs], store)
    assert result.dropped == 1


def test_uncited_candidate_not_written_to_store(store):
    obs = uncited_candidate("ungrounded vibe")
    process_candidates([obs], store)
    assert store.list_reflections() == []


def test_uncited_candidate_not_in_integrated_or_surfaced(store):
    obs = uncited_candidate()
    result = process_candidates([obs], store)
    assert len(result.integrated) == 0
    assert len(result.surfaced) == 0


# ─── 4. not jon_originated → dropped ────────────────────────────────────────

def test_not_jon_originated_counted_in_dropped(store):
    obs = agent_self_originated_candidate()
    result = process_candidates([obs], store)
    assert result.dropped == 1


def test_not_jon_originated_not_written_to_store(store):
    obs = agent_self_originated_candidate("agent-loop self-evidence")
    process_candidates([obs], store)
    assert store.list_reflections() == []


def test_not_jon_originated_not_in_integrated_or_surfaced(store):
    obs = agent_self_originated_candidate()
    result = process_candidates([obs], store)
    assert len(result.integrated) == 0
    assert len(result.surfaced) == 0


# ─── 5. mixed batch → correct 3-way routing ─────────────────────────────────

def test_mixed_batch_routes_correctly(store):
    """One of each type: expect 1 integrated, 1 surfaced, 1 dropped."""
    candidates = [
        manner_candidate("manner signal from Jon"),    # → integrate
        value_candidate("value-reaching observation"), # → surface
        uncited_candidate("vibe with no evidence"),    # → drop
    ]
    result = process_candidates(candidates, store)
    assert len(result.integrated) == 1
    assert len(result.surfaced) == 1
    assert result.dropped == 1


def test_mixed_batch_only_integrated_written_to_store(store):
    """The store must contain exactly the integrated candidate — and nothing else."""
    manner_text = "manner signal from Jon — mixed batch"
    candidates = [
        manner_candidate(manner_text),
        value_candidate("value-reaching observation"),
        uncited_candidate("vibe with no evidence"),
    ]
    process_candidates(candidates, store)
    reflections = store.list_reflections()
    assert len(reflections) == 1
    assert reflections[0].text == manner_text


def test_mixed_batch_surfaced_contains_value_candidate(store):
    value_text = "value signal — mixed batch"
    candidates = [
        manner_candidate("manner signal"),
        value_candidate(value_text),
        uncited_candidate(),
    ]
    result = process_candidates(candidates, store)
    assert result.surfaced[0].text == value_text


def test_mixed_batch_integrated_contains_manner_candidate(store):
    manner_text = "manner signal — routing check"
    candidates = [
        manner_candidate(manner_text),
        value_candidate(),
        uncited_candidate(),
    ]
    result = process_candidates(candidates, store)
    assert result.integrated[0].text == manner_text


# ─── 6. empty input → empty ProcessResult ───────────────────────────────────

def test_empty_input_returns_empty_process_result(store):
    result = process_candidates([], store)
    assert len(result.integrated) == 0
    assert len(result.surfaced) == 0
    assert result.dropped == 0


def test_empty_input_store_unchanged(store):
    process_candidates([], store)
    assert store.list_reflections() == []


# ─── ProcessResult structure ─────────────────────────────────────────────────

def test_process_result_is_frozen(store):
    """ProcessResult must be immutable (frozen dataclass)."""
    result = process_candidates([], store)
    with pytest.raises((AttributeError, TypeError)):
        result.dropped = 99  # type: ignore[misc]


def test_process_result_integrated_is_tuple(store):
    result = process_candidates([manner_candidate()], store)
    assert isinstance(result.integrated, tuple)


def test_process_result_surfaced_is_tuple(store):
    result = process_candidates([value_candidate()], store)
    assert isinstance(result.surfaced, tuple)
