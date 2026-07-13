"""Deterministic verification gate for SOVERYN vNext (v1 — Vett).

A recalled fact and a confabulated one come out of the identical mechanism —
sampling the next token — so the model cannot feel its own uncertainty. The
trigger to verify therefore cannot be left to model judgment; it must be an
external, deterministic mechanism. This package is that mechanism:

  - `detector` — a swappable `ClaimRiskSignal`. v1 is `HeuristicClaimDetector`,
    a pure, no-I/O, fail-safe-toward-flagging regex over verifiable-fact shapes.
  - `gate` — the finalization guard: if a risky answer was produced with no
    verify tool run this turn and budget remains, HOLD the answer, inject a
    corrective note, and continue the loop; on budget exhaustion, downgrade to
    the honest floor.

Public surface is intentionally small so v2 (self-policing uncertainty signal)
can drop in behind the same `ClaimRiskSignal` interface without touching the
gate or the loop.
"""

from __future__ import annotations

from soveryn.platform.verification.detector import (
    ClaimRiskSignal,
    HeuristicClaimDetector,
    RiskVerdict,
)
from soveryn.platform.verification.gate import (
    HONEST_FLOOR_ANSWER,
    VERIFY_TOOLS,
    GateDecision,
    VerificationGate,
)

__all__ = [
    "ClaimRiskSignal",
    "HeuristicClaimDetector",
    "RiskVerdict",
    "GateDecision",
    "VerificationGate",
    "VERIFY_TOOLS",
    "HONEST_FLOOR_ANSWER",
]
