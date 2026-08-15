"""Tests for the VerificationGate decision function (pure) + config.

Covers: fires on risky ∧ no-verify ∧ budget; passes when a verify tool ran;
respects budget / no-infinite-loop; honest-floor on exhaustion; owner scoping.
"""

import pytest

from soveryn.platform.verification.detector import RiskVerdict
from soveryn.platform.verification.gate import (
    HONEST_FLOOR_ANSWER,
    VERIFY_TOOLS,
    VerificationGate,
)


RISKY = "the ROMED8-2T is Intel and the RTX 5000 has 32GB"
CALM = "sure, I can help with that"


def test_gate_holds_on_risky_no_verify_with_budget():
    gate = VerificationGate()
    decision = gate.evaluate(
        answer_text=RISKY, question_text="q", tool_ledger=(), budget=2,
    )
    assert decision.action == "hold"
    assert decision.note is not None
    assert "system_probe" in decision.note
    # Must NOT coach the model to announce verification (permission theater).
    assert "Tell the user" not in (decision.note or "")
    assert "Call a tool NOW" in (decision.note or "")
    assert decision.verdict.risky is True


def test_gate_holds_on_intent_without_tool():
    """'Let me pull/verify…' with no tool call must HOLD, even if not a fact claim."""
    gate = VerificationGate()
    for text in (
        "Let me pull the current info on that.",
        "I'll check the latest specs and get back to you.",
        "I am running verification now.",
        "Shall I search for that?",
        "Give me a moment to look that up.",
    ):
        decision = gate.evaluate(
            answer_text=text, question_text="what's the latest?",
            tool_ledger=(), budget=2,
        )
        assert decision.action == "hold", text
        assert "NOW" in (decision.note or "")
        assert "intent_without_tool" in decision.verdict.markers


def test_gate_emits_intent_when_verify_tool_already_ran():
    gate = VerificationGate()
    decision = gate.evaluate(
        answer_text="Let me summarize what I found.",
        question_text="q",
        tool_ledger=("web_search",),
        budget=2,
    )
    # After a real tool ran, narration is fine — not theater.
    assert decision.action == "emit"


def test_gate_emits_when_verify_tool_ran():
    gate = VerificationGate()
    decision = gate.evaluate(
        answer_text=RISKY, question_text="q",
        tool_ledger=("system_probe",), budget=2,
    )
    assert decision.action == "emit"
    assert decision.answer == RISKY


def test_gate_emits_when_not_risky():
    gate = VerificationGate()
    decision = gate.evaluate(
        answer_text=CALM, question_text="q", tool_ledger=(), budget=2,
    )
    assert decision.action == "emit"
    assert decision.answer == CALM


def test_gate_emits_trivial_user_turn_even_with_intent_narration():
    """Greetings must not force tools — even if the draft says 'I'll check…'."""
    gate = VerificationGate()
    decision = gate.evaluate(
        answer_text="Hey! Let me check the boards for you.",
        question_text="hey",
        tool_ledger=(),
        budget=2,
    )
    assert decision.action == "emit"
    assert decision.answer == "Hey! Let me check the boards for you."


def test_gate_floors_on_budget_exhaustion():
    gate = VerificationGate()
    decision = gate.evaluate(
        answer_text=RISKY, question_text="q", tool_ledger=(), budget=0,
    )
    assert decision.action == "floor"
    assert decision.answer == HONEST_FLOOR_ANSWER


def test_any_verify_tool_counts():
    gate = VerificationGate()
    for tool in VERIFY_TOOLS:
        decision = gate.evaluate(
            answer_text=RISKY, question_text="q", tool_ledger=(tool,), budget=2,
        )
        assert decision.action == "emit", tool


def test_non_verify_tool_does_not_count():
    gate = VerificationGate()
    decision = gate.evaluate(
        answer_text=RISKY, question_text="q",
        tool_ledger=("read_file", "git_status"), budget=2,
    )
    assert decision.action == "hold"


def test_budget_sequence_is_bounded():
    """Simulate the loop: each hold decrements budget; after budget rounds the
    gate floors instead of holding forever (no infinite loop)."""
    gate = VerificationGate(forced_verify_budget=2)
    budget = gate.forced_verify_budget
    holds = 0
    for _ in range(10):  # far more than budget
        decision = gate.evaluate(
            answer_text=RISKY, question_text="q", tool_ledger=(), budget=budget,
        )
        if decision.action == "hold":
            holds += 1
            budget -= 1
            continue
        assert decision.action == "floor"
        break
    assert holds == 2  # exactly the budget, then floor


def test_default_budget_is_two():
    assert VerificationGate().forced_verify_budget == 2


def test_owner_scoping_defaults_to_vett_only():
    gate = VerificationGate()
    assert gate.applies_to("vett") is True
    assert gate.applies_to("Vett") is True
    assert gate.applies_to("aetheria") is False
    assert gate.applies_to("scotty") is False


def test_owner_set_is_configurable():
    gate = VerificationGate(owner_agents=frozenset({"vett", "aetheria"}))
    assert gate.applies_to("aetheria") is True
    assert gate.applies_to("scotty") is False


def test_negative_budget_rejected():
    with pytest.raises(ValueError):
        VerificationGate(forced_verify_budget=-1)


def test_custom_detector_is_used():
    class AlwaysRisky:
        def assess(self, *, answer_text, question_text):
            return RiskVerdict(risky=True, markers=("x",), reason="always")

    gate = VerificationGate(detector=AlwaysRisky())
    decision = gate.evaluate(
        answer_text="totally calm text", question_text="q",
        tool_ledger=(), budget=1,
    )
    assert decision.action == "hold"
