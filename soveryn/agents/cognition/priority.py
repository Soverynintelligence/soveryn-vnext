"""Priority trigger — immediate surface path for high-salience events.

Spec: docs/superpowers/specs/2026-06-22-continuous-cognition-design.md
      Phase 2, Task 2.5 — priority trigger.

## Contract (LOAD-BEARING)

`priority_trigger()` reflects on recent turns and returns the candidates
as a surface payload for immediate delivery to Jon.

It performs NO store writes — no write_reflection, no distill, no
write_note_version.  The sense-of-us baseline is NEVER touched by a
priority trigger.  Baseline integration stays disciplined and happens only
via the normal deep cycle (run_deep_cycle / cycle.py).

The full call chain is:
  1. Read store.current_note() for reflect context (read-only).
  2. Call reflect() to produce CandidateObservations.
  3. Return those observations directly as the surface payload.

Nothing is written.  The store state after priority_trigger is identical
to the store state before it.
"""

from __future__ import annotations

from typing import Callable

from soveryn.agents.cognition.reflect import reflect
from soveryn.agents.cognition.store import CognitionStore
from soveryn.agents.cognition.types import CandidateObservation, Turn

ChatFn = Callable[[str, str], str]
"""chat_fn(system: str, user: str) -> str — injected inference callable."""


def priority_trigger(
    agent: str,
    turns: list[Turn],
    store: CognitionStore,
    reflect_chat_fn: ChatFn,
) -> list[CandidateObservation]:
    """Run the priority (fast-surface) path for a high-salience event.

    Parameters
    ----------
    agent:
        Agent name ("aetheria", "vett", …). Forwarded to reflect() so the
        prompt is correctly attributed.

    turns:
        Recent high-salience conversation turns to reflect on.
        Empty list → returns [] immediately; reflect_chat_fn is not called.

    store:
        CognitionStore to read the current note from.  READ-ONLY — this
        function never calls any write method on the store.

    reflect_chat_fn:
        Injected inference callable for the reflection pass.
        Signature: chat_fn(system: str, user: str) -> str

    Returns
    -------
    list[CandidateObservation]
        The surface payload for immediate delivery to Jon.
        The store is UNTOUCHED — no baseline rewrite occurs.
    """
    if not turns:
        return []

    # Read-only: pull current note for reflect context (avoids redundancy).
    prior = store.current_note() or ""

    # Reflect — observe manner candidates from the high-salience turns.
    candidates = reflect(agent, turns, prior, reflect_chat_fn)

    # Return as surface payload.  No gate, no distill, no writes.
    return candidates
