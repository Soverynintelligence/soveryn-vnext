"""Tests for soveryn/app/services/narrative.py."""

from datetime import datetime, timezone

from soveryn.app.services.narrative import compose_greeting, GreetingInputs


def _at(hour: int) -> datetime:
    return datetime(2026, 5, 24, hour, 0, 0, tzinfo=timezone.utc)


def test_morning_greeting():
    g = compose_greeting(GreetingInputs(
        now=_at(7),
        recent_writes_by_agent={},
        recent_session_count=0,
    ))
    assert g.heading.startswith("Morning")


def test_afternoon_greeting():
    g = compose_greeting(GreetingInputs(
        now=_at(14),
        recent_writes_by_agent={},
        recent_session_count=0,
    ))
    assert g.heading.startswith("Afternoon")


def test_evening_greeting():
    g = compose_greeting(GreetingInputs(
        now=_at(20),
        recent_writes_by_agent={},
        recent_session_count=0,
    ))
    assert g.heading.startswith("Evening")


def test_quiet_body_when_no_activity():
    g = compose_greeting(GreetingInputs(
        now=_at(9),
        recent_writes_by_agent={},
        recent_session_count=0,
    ))
    assert "quiet" in g.body.lower() or "nothing" in g.body.lower()


def test_body_mentions_agent_writes():
    g = compose_greeting(GreetingInputs(
        now=_at(9),
        recent_writes_by_agent={"aetheria": 3, "vett": 1},
        recent_session_count=2,
    ))
    assert "aetheria" in g.body.lower()
    assert "3" in g.body


def test_body_singularizes_correctly():
    g = compose_greeting(GreetingInputs(
        now=_at(9),
        recent_writes_by_agent={"vett": 1},
        recent_session_count=0,
    ))
    assert "1 note" in g.body  # not "1 notes"


def test_body_pluralizes_correctly():
    g = compose_greeting(GreetingInputs(
        now=_at(9),
        recent_writes_by_agent={"vett": 5},
        recent_session_count=0,
    ))
    assert "5 notes" in g.body


def test_body_mentions_sessions_when_present():
    g = compose_greeting(GreetingInputs(
        now=_at(9),
        recent_writes_by_agent={},
        recent_session_count=4,
    ))
    assert "4" in g.body and "session" in g.body.lower()
