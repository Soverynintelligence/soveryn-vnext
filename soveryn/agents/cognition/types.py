"""Domain types for the Cognition pipeline.

Spec: docs/superpowers/specs/2026-06-22-continuous-cognition-design.md

All records are frozen dataclasses — immutable value objects. Nothing here
knows about the database; storage lives in CognitionStore.
"""

from __future__ import annotations

from dataclasses import dataclass


# ─── Node-type constants (the store allowlist) ───────────────────────────────

COGNITION_REFLECTION_NODE_TYPE = "cognition_reflection"
COGNITION_NOTE_NODE_TYPE = "cognition_note"

#: The complete set of node types this store is permitted to write.
#: Any type outside this set is rejected by CognitionStore._write.
COGNITION_NODE_TYPES: frozenset[str] = frozenset(
    {COGNITION_REFLECTION_NODE_TYPE, COGNITION_NOTE_NODE_TYPE}
)

#: The region tag that every cognition row MUST carry in its provenance JSON.
#: The write-isolation guard enforces this at the store boundary.
COGNITION_REGION = "cognition"


# ─── Errors ──────────────────────────────────────────────────────────────────

class CognitionWriteError(Exception):
    """Raised when the write-isolation guard blocks a write.

    This is the hard architectural guard: CognitionStore._write refuses
    any insert whose node_type is not in COGNITION_NODE_TYPES or whose
    provenance region is not COGNITION_REGION.  The public methods
    (write_reflection, write_note_version) always route through _write, so
    this guard is enforced end-to-end — not just on direct _write calls.

    The architectural promise: this store physically cannot write
    souls/persona/values; the worst it can do is a region="cognition" row.
    """


# ─── Pre-gate observation ────────────────────────────────────────────────────

@dataclass(frozen=True)
class CandidateObservation:
    """An observation from the reflection pipeline, before the worth-keeping gate.

    scope:
      "manner"  — eligible for self-application (tone, pacing, length, etc.)
      "value"   — must be surfaced to Jon, never silent self-edit
      "unsure"  — conservative default; treated as value-reaching

    citations:
      Conversation turn ids the observation is drawn from.  Evidence must
      come from Jon's signals — his words, his reactions — not from the
      agent's own outputs (jon_originated enforces this at gate layer).

    jon_originated:
      True  → evidence comes from Jon's signals (words, reactions).
      False → evidence comes from the agent's own output — MUST be rejected
              by the gate (anti-self-reinforcement rule, spec §worth-keeping-gate).
    """

    text: str
    scope: str                   # "manner" | "value" | "unsure"
    citations: tuple[str, ...]
    jon_originated: bool


# ─── Persisted forms ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ReflectionMemory:
    """The persisted, evidence-backed form of a candidate observation that passed
    the worth-keeping gate (or was explicitly stored for surfacing).

    Stored in the lattice nodes table as type='cognition_reflection' with
    provenance region='cognition'.  All fields except id/created_at are
    immutable; reverts work by writing a new note version, not editing rows.
    """

    id: str
    text: str
    scope: str                   # "manner" | "value" | "unsure"
    citations: tuple[str, ...]
    created_at: str


@dataclass(frozen=True)
class NoteVersion:
    """A single version of the sense-of-us note.

    Each deep-cycle rewrite creates a new NoteVersion; old versions are
    retained in the lattice for audit and one-click revert.  current_note()
    returns the content of the most-recent version.

    supersedes:
      The id of the NoteVersion this one replaces, or None if this is the
      first version.  Retained so the full version history is traversable
      without a timestamp scan.
    """

    id: str
    content: str
    created_at: str
    supersedes: str | None
