"""Worth-keeping gate for the continuous-cognition pipeline.

Spec: docs/superpowers/specs/2026-06-22-continuous-cognition-design.md
      "The worth-keeping gate"

Each candidate observation runs three checks in strict precedence order.
Failing any check prevents self-application:

1. EVIDENCE GROUNDING (citations required)
   An unevidenced candidate is rejected outright.  A citation must exist for
   each piece of evidence — "single-instance vibe" does not count.
   Rationale: tethers every integration to something real Jon said or did.

2. ECHO-CHAMBER GUARD (jon_originated required)
   The agent's own output cannot be evidence for a manner change.  Her
   behaviour cannot confirm itself — that's the loop that creates unbounded
   drift.  Only Jon's words and reactions are valid evidence.
   Rationale: anti-self-reinforcement rule; structural confab control.

3. SCOPE FENCE (manner / value / unsure)
   Manner observations are eligible for autonomous self-application.
   Value-reaching observations and uncertain scope (conservative default)
   are surfaced to Jon — never silently self-edited.
   Rationale: keeps autonomous adaptation bounded to communication style;
   values / identity stay anchored.

Relationship-scoping note (not enforced here — handled at injection):
  Cross-relationship generalisation is tagged scope="value" upstream at
  reflection time.  It therefore routes to SURFACE through rule 3.  The
  sense-of-us note is applied with-Jon-only at prompt-assembly; the gate
  itself is relationship-agnostic.
"""

from __future__ import annotations

from soveryn.agents.cognition.types import CandidateObservation

# ─── Verdict constants ────────────────────────────────────────────────────────
# Use these everywhere — never scatter string literals.

INTEGRATE = "integrate"
SURFACE   = "surface"
DROP      = "drop"

# ─── Scope routing table ──────────────────────────────────────────────────────
# Conservative default: anything not explicitly "manner" routes to SURFACE.

_SCOPE_VERDICT: dict[str, str] = {
    "manner": INTEGRATE,
    "value":  SURFACE,
    "unsure": SURFACE,   # conservative — when uncertain, never silent self-apply
}


# ─── Gate ─────────────────────────────────────────────────────────────────────

def gate(obs: CandidateObservation) -> str:
    """Return INTEGRATE | SURFACE | DROP for a candidate observation.

    Checks run in strict precedence order (see module docstring).
    The function is purely deterministic — it enforces policy on the
    structured fields the reflection model has already set; it contains
    no NLP / classification logic.
    """
    # 1. Evidence grounding — citations must be non-empty.
    if not obs.citations:
        return DROP

    # 2. Echo-chamber guard — evidence must come from Jon, not the agent itself.
    if not obs.jon_originated:
        return DROP

    # 3. Scope fence — route by scope; fall back to SURFACE for unknown values.
    return _SCOPE_VERDICT.get(obs.scope, SURFACE)
