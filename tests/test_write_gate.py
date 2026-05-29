"""Tests for provenance-aware lattice write gating."""

from __future__ import annotations

import pytest

from soveryn.platform.lattice import Region
from soveryn.platform.lattice.write_gate import WriteDecision, classify_write


def test_observational_episodic_write_is_auto():
    assert classify_write(region=Region.EPISODIC, kind="observation") is WriteDecision.AUTO


@pytest.mark.parametrize("kind", [
    "session_boundary",
    "timestamp",
    "factual_anchor",
    "procedural_step",
    "telemetry",
    "tool_output",
    "observation",
])
def test_structural_observational_kinds_are_auto(kind):
    assert classify_write(region=Region.SEMANTIC, kind=kind) is WriteDecision.AUTO


@pytest.mark.parametrize("region", [Region.IDENTITY, Region.AFFECTIVE])
def test_identity_and_affective_regions_always_require_confirmation(region):
    assert classify_write(region=region, kind="observation") is WriteDecision.CONFIRM
    assert classify_write(region=region, kind="tool_output") is WriteDecision.CONFIRM


@pytest.mark.parametrize("kind", [
    "relational_claim",
    "emotional_label",
    "prediction",
    "identity_shift",
    "long_term_preference",
    "high_salience_summary",
])
def test_interpretive_kinds_require_confirmation_regardless_of_region(kind):
    assert classify_write(region=Region.EPISODIC, kind=kind) is WriteDecision.CONFIRM
    assert classify_write(region=Region.SEMANTIC, kind=kind) is WriteDecision.CONFIRM
    assert classify_write(region=Region.PROCEDURAL, kind=kind) is WriteDecision.CONFIRM


def test_kind_normalization_is_case_and_separator_tolerant():
    assert classify_write(region=Region.EPISODIC, kind="Session Boundary") is WriteDecision.AUTO
    assert classify_write(region=Region.SEMANTIC, kind="relational-claim") is WriteDecision.CONFIRM


def test_unknown_kind_defaults_to_confirmation():
    assert classify_write(region=Region.SEMANTIC, kind="custom_summary") is WriteDecision.CONFIRM
