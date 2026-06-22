"""Tests for the worth-keeping gate (soveryn/agents/cognition/gate.py).

All tests are written BEFORE the implementation (TDD / RED phase).
Each test exercises one named behaviour from the spec; names match the
spec rationale so the test file doubles as a readable spec excerpt.

Spec: docs/superpowers/specs/2026-06-22-continuous-cognition-design.md
      "The worth-keeping gate"
"""

import pytest

from soveryn.agents.cognition.gate import gate, INTEGRATE, SURFACE, DROP
from soveryn.agents.cognition.types import CandidateObservation


# ─── helpers ─────────────────────────────────────────────────────────────────

def _obs(
    *,
    scope: str,
    citations: tuple[str, ...] = ("turn-1",),
    jon_originated: bool = True,
    text: str = "test observation",
) -> CandidateObservation:
    return CandidateObservation(
        text=text,
        scope=scope,
        citations=citations,
        jon_originated=jon_originated,
    )


# ─── Scope-fence: happy-path verdicts ────────────────────────────────────────

class TestScopeFenceHappyPath:
    def test_manner_cited_jon_originated_integrates(self):
        """Manner observations backed by Jon's evidence are self-applied."""
        obs = _obs(scope="manner")
        assert gate(obs) == INTEGRATE

    def test_value_cited_jon_originated_surfaces(self):
        """Value-reaching observations are surfaced to Jon, never silent self-edit."""
        obs = _obs(scope="value")
        assert gate(obs) == SURFACE

    def test_unsure_cited_jon_originated_surfaces(self):
        """Conservative default: when unsure, treat as value-reaching and surface."""
        obs = _obs(scope="unsure")
        assert gate(obs) == SURFACE


# ─── Evidence grounding: no citations → drop ─────────────────────────────────

class TestEvidenceGrounding:
    def test_no_citations_drops_regardless_of_manner_scope(self):
        """Unevidenced candidates are rejected even with a valid manner scope."""
        obs = _obs(scope="manner", citations=())
        assert gate(obs) == DROP

    def test_no_citations_drops_regardless_of_value_scope(self):
        """Unevidenced candidates are rejected regardless of scope."""
        obs = _obs(scope="value", citations=())
        assert gate(obs) == DROP

    def test_precedence_uncited_and_value_drops_not_surfaces(self):
        """Evidence check fires before scope check: uncited value → DROP, not SURFACE."""
        obs = _obs(scope="value", citations=())
        assert gate(obs) == DROP


# ─── Echo-chamber guard: not jon_originated → drop ───────────────────────────

class TestEchoChamberGuard:
    def test_not_jon_originated_drops_even_with_manner_scope_and_citations(self):
        """Agent's own output cannot be evidence for a manner change (anti-self-reinforcement)."""
        obs = _obs(scope="manner", citations=("turn-1",), jon_originated=False)
        assert gate(obs) == DROP

    def test_not_jon_originated_drops_even_with_value_scope_and_citations(self):
        """Agent's own output is never valid evidence, regardless of scope."""
        obs = _obs(scope="value", citations=("turn-1",), jon_originated=False)
        assert gate(obs) == DROP


# ─── Precedence: evidence fires before scope ─────────────────────────────────

class TestPrecedenceOrdering:
    def test_uncited_and_not_jon_originated_drops(self):
        """Both guards fail: still a single DROP (no double-surfacing)."""
        obs = _obs(scope="manner", citations=(), jon_originated=False)
        assert gate(obs) == DROP

    def test_cited_jon_originated_manner_is_not_dropped_or_surfaced(self):
        """Positive control: all guards pass for manner → INTEGRATE."""
        obs = _obs(scope="manner", citations=("t1", "t2"), jon_originated=True)
        assert gate(obs) == INTEGRATE

    def test_cited_jon_originated_unsure_is_not_dropped(self):
        """Positive control: all guards pass for unsure → SURFACE (not DROP)."""
        obs = _obs(scope="unsure", citations=("t1",), jon_originated=True)
        assert gate(obs) == SURFACE


# ─── Constant identity ────────────────────────────────────────────────────────

class TestVerdictConstants:
    def test_integrate_constant_is_string_integrate(self):
        assert INTEGRATE == "integrate"

    def test_surface_constant_is_string_surface(self):
        assert SURFACE == "surface"

    def test_drop_constant_is_string_drop(self):
        assert DROP == "drop"

    def test_gate_returns_one_of_three_verdicts(self):
        obs = _obs(scope="manner")
        result = gate(obs)
        assert result in {INTEGRATE, SURFACE, DROP}
