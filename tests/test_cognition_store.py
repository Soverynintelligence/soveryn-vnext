"""Tests for soveryn.agents.cognition — domain types + CognitionStore.

TDD: tests written FIRST. Covers:
  1. reflection write → read roundtrip (region, citations, scope, jon_originated)
  2. note version write; current_note() returns latest; ordering across 2 versions
  3. write-isolation negative test: non-cognition type OR region != "cognition"
     raises CognitionWriteError (the load-bearing architectural guard)

Fixture pattern mirrors test_coordination_store.py (LatticeStore init, then
store constructed over same path).
"""

import pytest

from soveryn.platform.lattice.legacy import LatticeStore
from soveryn.agents.cognition.types import (
    CandidateObservation,
    CognitionWriteError,
    NoteVersion,
    ReflectionMemory,
)
from soveryn.agents.cognition.store import CognitionStore


# ─── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def lattice_path(tmp_path):
    """Fresh lattice DB with the full schema initialized."""
    db_path = tmp_path / "test_cognition.db"
    LatticeStore(db_path)  # init schema (idempotent — same as coord tests)
    return db_path


@pytest.fixture
def store(lattice_path):
    return CognitionStore(lattice_path)


# ─── 1. Reflection write → read roundtrip ───────────────────────────────────

def test_write_reflection_returns_reflection_memory(store):
    obs = CandidateObservation(
        text="Jon reads hedging as noise",
        scope="manner",
        citations=("turn-001", "turn-003"),
        jon_originated=True,
    )
    mem = store.write_reflection(obs)
    assert isinstance(mem, ReflectionMemory)


def test_reflection_roundtrip_preserves_text(store):
    obs = CandidateObservation(
        text="Jon prefers direct answers",
        scope="manner",
        citations=("turn-010",),
        jon_originated=True,
    )
    mem = store.write_reflection(obs)
    mems = store.list_reflections()
    assert any(m.id == mem.id and m.text == "Jon prefers direct answers" for m in mems)


def test_reflection_roundtrip_preserves_scope(store):
    obs = CandidateObservation(
        text="Jon values autonomy",
        scope="value",
        citations=("turn-020",),
        jon_originated=True,
    )
    mem = store.write_reflection(obs)
    mems = store.list_reflections()
    match = next(m for m in mems if m.id == mem.id)
    assert match.scope == "value"


def test_reflection_roundtrip_preserves_citations(store):
    citations = ("turn-100", "turn-200", "turn-300")
    obs = CandidateObservation(
        text="Jon uses short, precise messages",
        scope="manner",
        citations=citations,
        jon_originated=True,
    )
    mem = store.write_reflection(obs)
    mems = store.list_reflections()
    match = next(m for m in mems if m.id == mem.id)
    assert match.citations == citations


def test_reflection_roundtrip_preserves_jon_originated_true(store):
    obs = CandidateObservation(
        text="Jon signals with short words",
        scope="manner",
        citations=("turn-001",),
        jon_originated=True,
    )
    mem = store.write_reflection(obs)
    mems = store.list_reflections()
    match = next(m for m in mems if m.id == mem.id)
    # jon_originated is part of provenance — verify it comes back
    # (ReflectionMemory doesn't carry it directly; verify via raw provenance)
    # Actually the spec says ReflectionMemory is the persisted form — we test
    # that the store stores it correctly by checking the provenance column.
    import json, sqlite3
    conn = sqlite3.connect(str(store.db_path))
    row = conn.execute("SELECT provenance FROM nodes WHERE id = ?", (mem.id,)).fetchone()
    conn.close()
    prov = json.loads(row[0])
    assert prov["jon_originated"] is True


def test_reflection_roundtrip_region_is_cognition(store):
    """The provenance region MUST be 'cognition' for every reflection row."""
    obs = CandidateObservation(
        text="Any text",
        scope="unsure",
        citations=("turn-x",),
        jon_originated=False,
    )
    mem = store.write_reflection(obs)
    import json, sqlite3
    conn = sqlite3.connect(str(store.db_path))
    row = conn.execute("SELECT provenance FROM nodes WHERE id = ?", (mem.id,)).fetchone()
    conn.close()
    prov = json.loads(row[0])
    assert prov["region"] == "cognition"


def test_list_reflections_empty_when_none_written(store):
    assert store.list_reflections() == []


def test_list_reflections_returns_multiple(store):
    for i in range(3):
        obs = CandidateObservation(
            text=f"observation {i}",
            scope="manner",
            citations=(f"turn-{i:03d}",),
            jon_originated=True,
        )
        store.write_reflection(obs)
    assert len(store.list_reflections()) == 3


# ─── 2. Note version write + current_note ordering ──────────────────────────

def test_write_note_version_returns_note_version(store):
    nv = store.write_note_version("Jon prefers brevity over ceremony.")
    assert isinstance(nv, NoteVersion)


def test_current_note_is_none_when_no_notes_written(store):
    assert store.current_note() is None


def test_current_note_returns_content_after_first_write(store):
    store.write_note_version("first note content")
    assert store.current_note() == "first note content"


def test_current_note_returns_latest_version(store):
    """When two notes are written, current_note returns the second (latest)."""
    store.write_note_version("version one")
    store.write_note_version("version two")
    assert store.current_note() == "version two"


def test_current_note_ordering_across_three_versions(store):
    store.write_note_version("a")
    store.write_note_version("b")
    store.write_note_version("c")
    assert store.current_note() == "c"


def test_note_version_supersedes_field_is_none_by_default(store):
    nv = store.write_note_version("content")
    assert nv.supersedes is None


def test_note_version_supersedes_carries_prior_id(store):
    first = store.write_note_version("v1")
    second = store.write_note_version("v2", supersedes=first.id)
    assert second.supersedes == first.id


def test_note_version_provenance_region_is_cognition(store):
    """Note version rows must also carry region='cognition' in provenance."""
    nv = store.write_note_version("the note")
    import json, sqlite3
    conn = sqlite3.connect(str(store.db_path))
    row = conn.execute("SELECT provenance FROM nodes WHERE id = ?", (nv.id,)).fetchone()
    conn.close()
    prov = json.loads(row[0])
    assert prov["region"] == "cognition"


# ─── 3. Write-isolation negative tests (the load-bearing guard) ─────────────

def test_write_isolation_rejects_non_cognition_type(store):
    """_write() with a node type not in the cognition allowlist MUST raise
    CognitionWriteError. This is the hard architectural guard."""
    with pytest.raises(CognitionWriteError):
        store._write(
            node_type="coordination",          # not a cognition type
            content="sneaky write",
            provenance={"region": "cognition"},
        )


def test_write_isolation_rejects_wrong_region(store):
    """_write() with region != 'cognition' in provenance MUST raise
    CognitionWriteError even if node_type is a cognition type."""
    with pytest.raises(CognitionWriteError):
        store._write(
            node_type="cognition_reflection",  # valid type
            content="sneaky region bypass",
            provenance={"region": "persona"},   # wrong region
        )


def test_write_isolation_rejects_missing_region(store):
    """_write() with no region key in provenance MUST also raise."""
    with pytest.raises(CognitionWriteError):
        store._write(
            node_type="cognition_reflection",
            content="no region at all",
            provenance={},
        )


def test_write_isolation_rejects_coordination_type_even_with_correct_region(store):
    """Type check is independent of region check — both must pass."""
    with pytest.raises(CognitionWriteError):
        store._write(
            node_type="lesson_learned",        # coordination type, not cognition
            content="bypass attempt",
            provenance={"region": "cognition"},
        )


def test_write_isolation_permits_cognition_reflection_type(store):
    """Valid cognition type + correct region must NOT raise."""
    mem_id = store._write(
        node_type="cognition_reflection",
        content="valid write",
        provenance={"region": "cognition", "scope": "manner", "citations": [], "jon_originated": True},
    )
    assert mem_id is not None


def test_write_isolation_permits_cognition_note_type(store):
    """cognition_note is also a permitted type."""
    note_id = store._write(
        node_type="cognition_note",
        content="valid note",
        provenance={"region": "cognition"},
    )
    assert note_id is not None


def test_public_write_reflection_cannot_bypass_isolation(store):
    """The public write_reflection always goes through _write, so isolation
    is enforced end-to-end — not just on direct _write calls."""
    # This is verified by the roundtrip tests passing; this test makes the
    # intent explicit: a correct observation must succeed (no CognitionWriteError).
    obs = CandidateObservation(
        text="manner observation",
        scope="manner",
        citations=("turn-1",),
        jon_originated=True,
    )
    mem = store.write_reflection(obs)  # must NOT raise
    assert mem.id is not None


def test_public_write_note_version_cannot_bypass_isolation(store):
    """write_note_version always goes through _write."""
    nv = store.write_note_version("safe note")  # must NOT raise
    assert nv.id is not None
