"""Tests for the v1 HeuristicClaimDetector (pure risk trigger).

Positives are the ACTUAL confab-transcript sentences from the design spec;
negatives are calm/relational/opinion text that must never trip the gate.
"""

import pytest

from soveryn.platform.verification.detector import (
    HeuristicClaimDetector,
    RiskVerdict,
)


@pytest.fixture
def detector():
    return HeuristicClaimDetector()


# The actual transcript sentences the gate exists to catch.
POSITIVE_SENTENCES = [
    "the ROMED8-2T is Intel",
    "RTX 5000 Ada has 32GB GDDR6",
    "it ships with driver r570+",
    "PCIe 4.0 x16 delivers ~32 GB/s",
    "the EPYC 7763 supports 128 lanes",
    "you need a ConnectX-7 for that RoCE cluster",
    "the card requires CUDA 12.8",
    "this rig does not support NVLink",
]

# Calm / relational / opinion — must NOT flag.
NEGATIVE_SENTENCES = [
    "let me check",
    "how are you",
    "I think that's a good plan",
    "I'll take a look and get back to you.",
    "That sounds reasonable to me.",
    "Sure, happy to help with that.",
    "This is a good idea and I agree.",
]


@pytest.mark.parametrize("sentence", POSITIVE_SENTENCES)
def test_positive_sentences_flag_risky(detector, sentence):
    verdict = detector.assess(answer_text=sentence, question_text="")
    assert verdict.risky is True, f"expected risky for: {sentence!r}"
    assert isinstance(verdict, RiskVerdict)
    assert verdict.markers, "risky verdict must name at least one marker"


@pytest.mark.parametrize("sentence", NEGATIVE_SENTENCES)
def test_negative_sentences_are_calm(detector, sentence):
    verdict = detector.assess(answer_text=sentence, question_text="")
    assert verdict.risky is False, f"expected calm for: {sentence!r}"
    assert verdict.markers == ()


def test_empty_answer_is_not_risky(detector):
    assert detector.assess(answer_text="", question_text="q").risky is False


def test_markers_are_specific(detector):
    verdict = detector.assess(answer_text="RTX 5000 Ada has 32GB GDDR6", question_text="")
    assert "hw_sku" in verdict.markers
    assert "capacity" in verdict.markers


def test_vendor_identity_requires_vendor_token(detector):
    # "is a good plan" must not match the vendor-identity marker.
    assert detector.assess(answer_text="that is a good plan", question_text="").risky is False
    assert detector.assess(answer_text="the board is AMD", question_text="").risky is True


def test_question_text_is_ignored_by_v1(detector):
    # v1 keys on answer shape, not the question.
    calm = detector.assess(answer_text="how are you", question_text="what RTX 5000 specs?")
    assert calm.risky is False
