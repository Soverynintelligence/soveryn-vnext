"""Pure barge-in policy decisions (PR4a)."""

from __future__ import annotations

from soveryn.platform.voice.turn_policy import should_accept_barge


def test_accept_when_enabled_bot_speaking_and_past_min():
    d = should_accept_barge(
        barge_in_enabled=True,
        bot_speaking=True,
        speech_ms=150.0,
        min_barge_ms=150,
    )
    assert d.accept is True
    assert d.reason == "accepted"


def test_reject_when_disabled():
    d = should_accept_barge(
        barge_in_enabled=False,
        bot_speaking=True,
        speech_ms=500.0,
        min_barge_ms=150,
    )
    assert d.accept is False
    assert d.reason == "disabled"


def test_reject_when_bot_not_speaking():
    d = should_accept_barge(
        barge_in_enabled=True,
        bot_speaking=False,
        speech_ms=500.0,
        min_barge_ms=150,
    )
    assert d.accept is False
    assert d.reason == "not_bot_speaking"


def test_reject_below_min_barge():
    d = should_accept_barge(
        barge_in_enabled=True,
        bot_speaking=True,
        speech_ms=149.9,
        min_barge_ms=150,
    )
    assert d.accept is False
    assert d.reason == "below_min_barge"


def test_reject_already_pending():
    d = should_accept_barge(
        barge_in_enabled=True,
        bot_speaking=True,
        speech_ms=500.0,
        min_barge_ms=150,
        interrupt_pending=True,
    )
    assert d.accept is False
    assert d.reason == "already_pending"
