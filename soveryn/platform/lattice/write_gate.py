"""Pure write-gate policy for provenance-aware memory writes."""

from __future__ import annotations

from enum import StrEnum

from soveryn.platform.lattice.types import Region


class WriteDecision(StrEnum):
    """Decision for whether a memory write may land canonically now."""

    AUTO = "auto"
    CONFIRM = "confirm"


_STRUCTURAL_KINDS = frozenset({
    "session_boundary",
    "timestamp",
    "factual_anchor",
    "procedural_step",
    "telemetry",
    "tool_output",
    "observation",
})

_INTERPRETIVE_KINDS = frozenset({
    "relational_claim",
    "emotional_label",
    "prediction",
    "identity_shift",
    "long_term_preference",
    "high_salience_summary",
})

_ALWAYS_CONFIRM_REGIONS = frozenset({Region.IDENTITY, Region.AFFECTIVE})


def classify_write(*, region: Region, kind: str) -> WriteDecision:
    """Classify a candidate write using the locked Phase 2b-i gate policy."""

    normalized_region = region if isinstance(region, Region) else Region(str(region))
    normalized_kind = _normalize_kind(kind)
    if normalized_region in _ALWAYS_CONFIRM_REGIONS:
        return WriteDecision.CONFIRM
    if normalized_kind in _INTERPRETIVE_KINDS:
        return WriteDecision.CONFIRM
    if normalized_kind in _STRUCTURAL_KINDS:
        return WriteDecision.AUTO
    return WriteDecision.CONFIRM


def _normalize_kind(kind: str) -> str:
    return kind.strip().lower().replace("-", "_").replace(" ", "_")
