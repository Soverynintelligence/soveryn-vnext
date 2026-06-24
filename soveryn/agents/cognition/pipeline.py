"""Cognition pipeline — routes candidate observations by gate verdict.

Spec: docs/superpowers/specs/2026-06-22-continuous-cognition-design.md
      "Data flow" + "The worth-keeping gate"

This module wires the already-built pieces:
  gate(obs) → verdict → integrate|surface|drop

  integrate → store.write_reflection(obs)  → collect ReflectionMemory
  surface   → collect CandidateObservation (delivery to Jon is a later concern)
  drop      → increment counter

Uses gate.py verdict constants (INTEGRATE / SURFACE / DROP) — never hardcoded
string literals.
"""

from __future__ import annotations

from dataclasses import dataclass

from soveryn.agents.cognition.gate import DROP, INTEGRATE, SURFACE, gate
from soveryn.agents.cognition.store import CognitionStore
from soveryn.agents.cognition.types import CandidateObservation, ReflectionMemory


# ─── Result type ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ProcessResult:
    """Immutable result of a process_candidates() run.

    integrated: observations the gate passed and that were written to the store.
    surfaced:   value-reaching / uncertain observations held for Jon to review.
    dropped:    count of observations rejected by the gate (no citation or
                agent-self-originated evidence).
    """

    integrated: tuple[ReflectionMemory, ...]
    surfaced: tuple[CandidateObservation, ...]
    dropped: int


# ─── Pipeline entry point ────────────────────────────────────────────────────

def process_candidates(
    candidates: list[CandidateObservation],
    store: CognitionStore,
) -> ProcessResult:
    """Run each candidate through the gate and route by verdict.

    Args:
        candidates: Zero or more pre-reflection candidate observations.
        store:      CognitionStore instance to persist integrated observations.

    Returns:
        ProcessResult with the outcomes of all routing decisions.
    """
    integrated: list[ReflectionMemory] = []
    surfaced: list[CandidateObservation] = []
    dropped: int = 0

    for obs in candidates:
        verdict = gate(obs)

        if verdict == INTEGRATE:
            mem = store.write_reflection(obs)
            integrated.append(mem)

        elif verdict == SURFACE:
            surfaced.append(obs)

        elif verdict == DROP:
            dropped += 1

        # Any unknown verdict from a future gate version is conservatively
        # treated as DROP — never silently promotes to integrate.
        else:
            dropped += 1

    return ProcessResult(
        integrated=tuple(integrated),
        surfaced=tuple(surfaced),
        dropped=dropped,
    )
