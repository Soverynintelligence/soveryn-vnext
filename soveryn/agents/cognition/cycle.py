"""Deep cognition cycle — orchestrates reflect → gate/process → distill.

Spec: docs/superpowers/specs/2026-06-22-continuous-cognition-design.md
      Phase 2, Task 2.4 — deep cognition cycle.

## What this module does

`run_deep_cycle()` composes the three already-built cognition pieces into one
coherent pass:

  1. reflect()           — observe manner candidates from recent turns
  2. process_candidates() — gate them (integrate | surface | drop) and persist
  3. distill()           — synthesize current reflections into the sense-of-us note

This is the testable orchestration heart of the continuous-cognition system.

## What this module does NOT do

No scheduling, no timers, no real-time tier.  Those are separate follow tasks.
`run_deep_cycle()` is a pure synchronous function: call it when you want a cycle;
it does one pass and returns.

## Separate chat_fns (load-bearing seam)

reflect_chat_fn and distill_chat_fn are injected separately.  In production
they may point at the same model (:8091), but the seam is kept clean so each
can be routed independently if needed (e.g. different temperature, different
model for each role).

## Decay semantics (from distill.py contract)

distill() synthesizes from store.list_reflections() — the CURRENT set.
Stale reflections that are no longer reinforced simply do not appear in the new
note because the model does not re-synthesize them.  The cycle does not
explicitly expire rows; absence from the new note is the decay mechanism.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from soveryn.agents.cognition.distill import distill
from soveryn.agents.cognition.pipeline import ProcessResult, process_candidates
from soveryn.agents.cognition.reflect import reflect
from soveryn.agents.cognition.store import CognitionStore
from soveryn.agents.cognition.types import NoteVersion, Turn

# ─── Type aliases ─────────────────────────────────────────────────────────────

ChatFn = Callable[[str, str], str]
"""chat_fn(system: str, user: str) -> str — injected inference callable."""


# ─── Result type ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CycleResult:
    """Immutable result of one deep cognition cycle.

    candidate_count:
        Total number of CandidateObservations returned by reflect(), before
        the gate.  Zero means reflect short-circuited (empty turns) or the
        model emitted no candidates.

    process:
        The routing result from process_candidates(): .integrated, .surfaced,
        .dropped.

    note:
        The NoteVersion written by distill(), or None if distill was skipped
        (memories was empty) or distill returned None (empty model response).
    """

    candidate_count: int
    process: ProcessResult
    note: NoteVersion | None


# ─── Public API ───────────────────────────────────────────────────────────────

def run_deep_cycle(
    agent: str,
    turns: list[Turn],
    store: CognitionStore,
    reflect_chat_fn: ChatFn,
    distill_chat_fn: ChatFn,
) -> CycleResult:
    """Run one deep cognition cycle: reflect → process → distill.

    Parameters
    ----------
    agent:
        Agent name ("aetheria", "vett", …). Forwarded to reflect() and
        distill() so each prompt is correctly attributed.

    turns:
        Recent conversation turns to reflect on.  If empty, reflect()
        short-circuits and returns []; distill() is not called.

    store:
        CognitionStore to read the prior note from, persist integrated
        reflections to, and write the new note version to.

    reflect_chat_fn:
        Injected inference callable for the reflection pass.
        Signature: chat_fn(system: str, user: str) -> str

    distill_chat_fn:
        Injected inference callable for the distillation pass.
        Signature: chat_fn(system: str, user: str) -> str
        May be the same object as reflect_chat_fn in production.

    Returns
    -------
    CycleResult
        Frozen dataclass with candidate_count, process, and note.
    """
    # Step 1: read prior note to pass into reflect so it avoids redundancy.
    prior = store.current_note() or ""

    # Step 2: reflect — observe manner candidates from recent turns.
    # reflect() returns [] immediately if turns is empty.
    candidates = reflect(agent, turns, prior, reflect_chat_fn)

    # Step 3: gate + persist — routes each candidate and writes integrations.
    result = process_candidates(candidates, store)

    # Step 4: fetch the current set of reflections for distillation.
    # This is the post-integration snapshot — newly integrated rows are present.
    memories = store.list_reflections()

    # Step 5: distill — synthesize into the sense-of-us note.
    # distill() returns None if memories is empty (guards against fabrication).
    note = distill(agent, memories, store, distill_chat_fn) if memories else None

    return CycleResult(
        candidate_count=len(candidates),
        process=result,
        note=note,
    )
