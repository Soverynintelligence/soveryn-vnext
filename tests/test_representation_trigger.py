"""Tests for representation trigger eligibility logic.

Pure function tests — no I/O, no DB, no HTTP.
"""
from __future__ import annotations

import pytest

from soveryn.agents.representation.config import RepresentationConfig
from soveryn.agents.representation.trigger import Eligibility, evaluate


def _cfg(**kwargs) -> RepresentationConfig:
    return RepresentationConfig(**kwargs)


# ── Below min_turns ────────────────────────────────────────────────────────────

def test_evaluate_zero_turns_not_eligible():
    cfg = _cfg(enabled=True, min_turns=4)
    result = evaluate(0, cfg)
    assert result.eligible is False
    assert result.skip_reason == "below_min_turns"


def test_evaluate_below_min_turns_not_eligible():
    cfg = _cfg(enabled=True, min_turns=4)
    result = evaluate(3, cfg)
    assert result.eligible is False
    assert result.skip_reason == "below_min_turns"


# ── Exactly at min_turns ───────────────────────────────────────────────────────

def test_evaluate_at_min_turns_eligible():
    cfg = _cfg(enabled=True, min_turns=4)
    result = evaluate(4, cfg)
    assert result.eligible is True
    assert result.skip_reason is None


def test_evaluate_above_min_turns_eligible():
    cfg = _cfg(enabled=True, min_turns=4)
    result = evaluate(10, cfg)
    assert result.eligible is True
    assert result.skip_reason is None


# ── Disabled ───────────────────────────────────────────────────────────────────

def test_evaluate_disabled_not_eligible():
    cfg = _cfg(enabled=False, min_turns=4)
    result = evaluate(10, cfg)
    assert result.eligible is False
    assert result.skip_reason == "disabled"


def test_evaluate_disabled_zero_turns_not_eligible():
    cfg = _cfg(enabled=False, min_turns=0)
    result = evaluate(0, cfg)
    assert result.eligible is False
    assert result.skip_reason == "disabled"


# ── Disabled check precedes min_turns check ──────────────────────────────────

def test_disabled_takes_precedence_over_below_min():
    """disabled check fires before min_turns check."""
    cfg = _cfg(enabled=False, min_turns=100)
    result = evaluate(0, cfg)
    assert result.skip_reason == "disabled"


# ── Eligibility dataclass is frozen (hashable) ────────────────────────────────

def test_eligibility_frozen():
    cfg = _cfg(enabled=True, min_turns=1)
    result = evaluate(5, cfg)
    with pytest.raises(Exception):
        result.eligible = False  # type: ignore[misc]
