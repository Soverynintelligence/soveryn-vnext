"""Tests for soveryn.agents.cognition.distill — sense-of-us note distillation.

TDD: tests written FIRST (RED phase before distill.py exists).

Spec: docs/superpowers/specs/2026-06-22-continuous-cognition-design.md
      "Consolidation + decay", "ambient not instruction",
      sense-of-us note / bounded rewrite.

Verified behaviors:
  1. Basic write: fake chat_fn returns short note → NoteVersion written;
     store.current_note() returns that content.
  2. Supersedes chain: second distill points at the first NoteVersion's id;
     current_note() returns the newer content.
  3. Size cap: model returns more than max_lines non-empty lines → stored
     content is truncated to max_lines non-empty lines.
  4. Fence stripping: model wraps output in ``` fences → fences stripped
     from stored content.
  5. Empty memories → no new NoteVersion written; current_note() returns
     whatever was there before (None if nothing; old content if something).

All tests use a fake chat_fn — no real model call ever made.
Fixture pattern: LatticeStore(tmp_path) → CognitionStore(tmp_path).
"""

from __future__ import annotations

import pytest

from soveryn.platform.lattice.legacy import LatticeStore
from soveryn.agents.cognition.types import (
    CandidateObservation,
    NoteVersion,
    ReflectionMemory,
)
from soveryn.agents.cognition.store import CognitionStore
from soveryn.agents.cognition.distill import distill


# ─── fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def lattice_path(tmp_path):
    """Fresh lattice DB with full schema initialized."""
    db_path = tmp_path / "test_distill.db"
    LatticeStore(db_path)
    return db_path


@pytest.fixture
def store(lattice_path):
    return CognitionStore(lattice_path)


def _make_memory(text: str, index: int = 1) -> ReflectionMemory:
    """Construct a minimal valid ReflectionMemory for feeding into distill."""
    return ReflectionMemory(
        id=f"mem-{index:03d}",
        text=text,
        scope="manner",
        citations=(f"turn-{index:03d}",),
        jon_originated=True,
        created_at=f"2026-06-22T10:{index:02d}:00",
    )


def _chat_fn_returning(text: str):
    """Return a chat_fn that always yields the given text."""
    def _fn(system: str, user: str) -> str:
        return text
    return _fn


# ─── 1. Basic write ──────────────────────────────────────────────────────────


class TestBasicWrite:
    """distill() writes a NoteVersion; current_note() returns that content."""

    def test_returns_note_version(self, store):
        memories = [_make_memory("Jon reads hedging as noise")]
        note_text = "Jon reads hedging as noise."
        result = distill(
            agent="aetheria",
            memories=memories,
            store=store,
            chat_fn=_chat_fn_returning(note_text),
        )
        assert isinstance(result, NoteVersion)

    def test_current_note_reflects_distilled_content(self, store):
        memories = [_make_memory("Jon reads hedging as noise")]
        note_text = "Jon reads hedging as noise."
        distill(
            agent="aetheria",
            memories=memories,
            store=store,
            chat_fn=_chat_fn_returning(note_text),
        )
        assert store.current_note() == note_text

    def test_stored_content_matches_returned_note_version_content(self, store):
        memories = [_make_memory("Jon prefers concise answers")]
        note_text = "Jon prefers concise answers."
        result = distill(
            agent="aetheria",
            memories=memories,
            store=store,
            chat_fn=_chat_fn_returning(note_text),
        )
        assert result.content == note_text


# ─── 2. Supersedes chain ─────────────────────────────────────────────────────


class TestSupersedesChain:
    """Second distill supersedes the first; current_note() returns the newer."""

    def test_second_distill_supersedes_first(self, store):
        memories_v1 = [_make_memory("Jon reads hedging as noise", 1)]
        note_v1_text = "Jon reads hedging as noise."

        v1 = distill(
            agent="aetheria",
            memories=memories_v1,
            store=store,
            chat_fn=_chat_fn_returning(note_v1_text),
        )

        memories_v2 = [
            _make_memory("Jon reads hedging as noise", 1),
            _make_memory("Jon likes direct phrasing", 2),
        ]
        note_v2_text = "Jon reads hedging as noise.\nJon likes direct phrasing."

        v2 = distill(
            agent="aetheria",
            memories=memories_v2,
            store=store,
            chat_fn=_chat_fn_returning(note_v2_text),
        )

        # v2 must point at v1 as the superseded version
        assert v2.supersedes == v1.id

    def test_current_note_returns_newer_after_second_distill(self, store):
        memories_v1 = [_make_memory("First observation", 1)]
        v1_text = "First observation."
        distill(
            agent="aetheria",
            memories=memories_v1,
            store=store,
            chat_fn=_chat_fn_returning(v1_text),
        )

        memories_v2 = [_make_memory("Second observation", 2)]
        v2_text = "Second observation."
        distill(
            agent="aetheria",
            memories=memories_v2,
            store=store,
            chat_fn=_chat_fn_returning(v2_text),
        )

        assert store.current_note() == v2_text

    def test_first_distill_has_no_supersedes(self, store):
        memories = [_make_memory("Only observation", 1)]
        v1 = distill(
            agent="aetheria",
            memories=memories,
            store=store,
            chat_fn=_chat_fn_returning("Only observation."),
        )
        assert v1.supersedes is None


# ─── 3. Size cap enforcement ──────────────────────────────────────────────────


class TestSizeCap:
    """Model returns more than max_lines non-empty lines → truncated in store."""

    def test_oversized_note_is_truncated_to_max_lines(self, store):
        # Build a 10-line note; max_lines=5 → only 5 lines stored
        lines = [f"Observation line {i}." for i in range(1, 11)]
        oversized_text = "\n".join(lines)
        memories = [_make_memory("some memory", 1)]

        result = distill(
            agent="aetheria",
            memories=memories,
            store=store,
            chat_fn=_chat_fn_returning(oversized_text),
            max_lines=5,
        )

        stored_lines = [l for l in result.content.splitlines() if l.strip()]
        assert len(stored_lines) == 5

    def test_truncation_keeps_first_lines(self, store):
        lines = [f"Line {i}." for i in range(1, 11)]
        oversized_text = "\n".join(lines)
        memories = [_make_memory("some memory", 1)]

        result = distill(
            agent="aetheria",
            memories=memories,
            store=store,
            chat_fn=_chat_fn_returning(oversized_text),
            max_lines=3,
        )

        # The first 3 non-empty lines should be retained
        expected = "\n".join(lines[:3])
        assert result.content == expected

    def test_note_within_cap_not_truncated(self, store):
        lines = ["Line 1.", "Line 2.", "Line 3."]
        note_text = "\n".join(lines)
        memories = [_make_memory("some memory", 1)]

        result = distill(
            agent="aetheria",
            memories=memories,
            store=store,
            chat_fn=_chat_fn_returning(note_text),
            max_lines=8,
        )

        stored_lines = [l for l in result.content.splitlines() if l.strip()]
        assert len(stored_lines) == 3

    def test_blank_lines_do_not_count_toward_cap(self, store):
        # 3 non-empty lines separated by blanks; max_lines=8 → all 3 kept
        text_with_blanks = "Line 1.\n\nLine 2.\n\n\nLine 3."
        memories = [_make_memory("some memory", 1)]

        result = distill(
            agent="aetheria",
            memories=memories,
            store=store,
            chat_fn=_chat_fn_returning(text_with_blanks),
            max_lines=8,
        )

        non_empty = [l for l in result.content.splitlines() if l.strip()]
        assert len(non_empty) == 3


# ─── 4. Fence stripping ───────────────────────────────────────────────────────


class TestFenceStripping:
    """Model wraps output in ``` fences → fences stripped from stored content."""

    def test_backtick_fence_stripped(self, store):
        note_text = "Jon reads hedging as noise."
        fenced = f"```\n{note_text}\n```"
        memories = [_make_memory("some memory", 1)]

        result = distill(
            agent="aetheria",
            memories=memories,
            store=store,
            chat_fn=_chat_fn_returning(fenced),
        )

        assert result.content == note_text

    def test_named_fence_stripped(self, store):
        note_text = "Jon reads hedging as noise."
        fenced = f"```markdown\n{note_text}\n```"
        memories = [_make_memory("some memory", 1)]

        result = distill(
            agent="aetheria",
            memories=memories,
            store=store,
            chat_fn=_chat_fn_returning(fenced),
        )

        assert result.content == note_text

    def test_fenced_multi_line_stripped(self, store):
        lines = "Jon reads hedging as noise.\nJon prefers short answers."
        fenced = f"```\n{lines}\n```"
        memories = [_make_memory("some memory", 1)]

        result = distill(
            agent="aetheria",
            memories=memories,
            store=store,
            chat_fn=_chat_fn_returning(fenced),
        )

        assert result.content == lines

    def test_unfenced_content_unchanged(self, store):
        note_text = "Jon reads hedging as noise."
        memories = [_make_memory("some memory", 1)]

        result = distill(
            agent="aetheria",
            memories=memories,
            store=store,
            chat_fn=_chat_fn_returning(note_text),
        )

        assert result.content == note_text


# ─── 5. Empty memories ────────────────────────────────────────────────────────


class TestEmptyMemories:
    """Empty memories list: no new NoteVersion written; prior note preserved.

    Rationale: distilling zero evidence into a note would fabricate content
    (violates the ambient-observation / Jon-originated-evidence rules). The
    right behavior is to skip the write entirely and leave current_note() at
    whatever was already there — None if brand new, or the last good note.
    """

    def test_empty_memories_with_no_prior_note_returns_none_current_note(self, store):
        # No prior note, no memories → current_note stays None
        result = distill(
            agent="aetheria",
            memories=[],
            store=store,
            chat_fn=_chat_fn_returning("should not be called"),
        )
        # Either returns the prior NoteVersion (None → no version) or None
        # The important invariant: current_note() is still None
        assert store.current_note() is None

    def test_empty_memories_preserves_prior_note(self, store):
        # Write a prior note first
        prior_memories = [_make_memory("Jon reads hedging as noise", 1)]
        prior_text = "Jon reads hedging as noise."
        distill(
            agent="aetheria",
            memories=prior_memories,
            store=store,
            chat_fn=_chat_fn_returning(prior_text),
        )

        # Now distill with empty memories → prior note must be unchanged
        distill(
            agent="aetheria",
            memories=[],
            store=store,
            chat_fn=_chat_fn_returning("fabricated content — must not appear"),
        )

        assert store.current_note() == prior_text

    def test_empty_memories_chat_fn_not_called(self, store):
        """chat_fn must not be invoked when there is nothing to synthesize."""
        call_count = {"n": 0}

        def _tracking_fn(system: str, user: str) -> str:
            call_count["n"] += 1
            return "should never be stored"

        distill(
            agent="aetheria",
            memories=[],
            store=store,
            chat_fn=_tracking_fn,
        )

        assert call_count["n"] == 0
