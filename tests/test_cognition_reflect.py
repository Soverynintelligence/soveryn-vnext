"""Tests for the manner-reflection pipeline (soveryn/agents/cognition/reflect.py).

Written BEFORE the implementation (TDD / RED phase).

Spec: docs/superpowers/specs/2026-06-22-continuous-cognition-design.md
      "manner-reflection pipeline", "worth-keeping gate", "scope fence"

All tests use a fake chat_fn — no real model call ever made.  The fake
callable matches the expected signature: chat_fn(system: str, user: str) -> str.
"""

import json
import pytest

from soveryn.agents.cognition.types import CandidateObservation, Turn
from soveryn.agents.cognition.reflect import reflect


# ─── fake chat_fn helpers ─────────────────────────────────────────────────────

def _chat_fn_returning(payload: object):
    """Return a chat_fn that always yields the JSON-serialised payload."""
    raw = json.dumps(payload)
    def _fn(system: str, user: str) -> str:
        return raw
    return _fn


def _chat_fn_returning_raw(raw: str):
    """Return a chat_fn that always yields raw (possibly non-JSON) text."""
    def _fn(system: str, user: str) -> str:
        return raw
    return _fn


# ─── fixtures ─────────────────────────────────────────────────────────────────

def _turns(*role_content_pairs: tuple[str, str]) -> list[Turn]:
    return [
        Turn(turn_id=f"t{i}", role=r, content=c)
        for i, (r, c) in enumerate(role_content_pairs, start=1)
    ]


# ─── Happy-path: well-formed JSON array from model ───────────────────────────

class TestWellFormedResponse:
    """reflect() parses a canned JSON array into CandidateObservations."""

    def test_single_manner_observation_parsed_correctly(self):
        payload = [
            {
                "text": "Jon prefers concise answers without hedging.",
                "scope": "manner",
                "citations": ["t1", "t2"],
                "jon_originated": True,
            }
        ]
        turns = _turns(("user", "just tell me directly"), ("assistant", "Sure..."))
        result = reflect(
            agent="aetheria",
            turns=turns,
            prior_note="",
            chat_fn=_chat_fn_returning(payload),
        )
        assert len(result) == 1
        obs = result[0]
        assert isinstance(obs, CandidateObservation)
        assert obs.text == "Jon prefers concise answers without hedging."
        assert obs.scope == "manner"
        assert obs.citations == ("t1", "t2")
        assert obs.jon_originated is True

    def test_multiple_observations_parsed(self):
        payload = [
            {
                "text": "Jon reads hedging as noise.",
                "scope": "manner",
                "citations": ["t1"],
                "jon_originated": True,
            },
            {
                "text": "Jon values directness deeply.",
                "scope": "value",
                "citations": ["t2"],
                "jon_originated": True,
            },
            {
                "text": "Not sure if this is manner or values.",
                "scope": "unsure",
                "citations": ["t1", "t3"],
                "jon_originated": False,
            },
        ]
        turns = _turns(
            ("user", "stop hedging"),
            ("assistant", "Ok."),
            ("user", "and be direct"),
        )
        result = reflect(
            agent="aetheria",
            turns=turns,
            prior_note="Prior: some note.",
            chat_fn=_chat_fn_returning(payload),
        )
        assert len(result) == 3
        scopes = [obs.scope for obs in result]
        assert scopes == ["manner", "value", "unsure"]
        assert result[2].jon_originated is False

    def test_citations_preserved_as_tuple(self):
        """citations from JSON array become a tuple[str,...] on CandidateObservation."""
        payload = [
            {
                "text": "something",
                "scope": "manner",
                "citations": ["t1", "t2", "t3"],
                "jon_originated": True,
            }
        ]
        turns = _turns(("user", "hi"), ("assistant", "hey"))
        result = reflect(
            agent="aetheria",
            turns=turns,
            prior_note="",
            chat_fn=_chat_fn_returning(payload),
        )
        assert result[0].citations == ("t1", "t2", "t3")
        assert isinstance(result[0].citations, tuple)

    def test_jon_originated_false_parsed_correctly(self):
        """jon_originated=False is preserved as False, not coerced."""
        payload = [
            {
                "text": "Agent said something confident.",
                "scope": "manner",
                "citations": ["t1"],
                "jon_originated": False,
            }
        ]
        turns = _turns(("user", "ok"), ("assistant", "yes"))
        result = reflect(
            agent="aetheria",
            turns=turns,
            prior_note="",
            chat_fn=_chat_fn_returning(payload),
        )
        assert result[0].jon_originated is False


# ─── Empty turns → no model call needed, returns [] ─────────────────────────

class TestEmptyTurns:
    """reflect() with empty turns returns [] without calling the model."""

    def test_empty_turns_returns_empty_list(self):
        called = []
        def _tracking_fn(system: str, user: str) -> str:
            called.append(1)
            return "[]"

        result = reflect(
            agent="aetheria",
            turns=[],
            prior_note="",
            chat_fn=_tracking_fn,
        )
        assert result == []

    def test_empty_turns_does_not_call_chat_fn(self):
        """Fast-path: model is not called when there is nothing to reflect on."""
        called = []
        def _tracking_fn(system: str, user: str) -> str:
            called.append(1)
            return "[]"

        reflect(agent="aetheria", turns=[], prior_note="", chat_fn=_tracking_fn)
        assert called == [], "chat_fn should not be invoked for empty turns"


# ─── Malformed JSON → no exception, returns [] ───────────────────────────────

class TestMalformedJSON:
    """reflect() handles bad model output without raising."""

    def test_non_json_output_returns_empty_list(self):
        result = reflect(
            agent="aetheria",
            turns=_turns(("user", "hi")),
            prior_note="",
            chat_fn=_chat_fn_returning_raw("I cannot comply."),
        )
        assert result == []

    def test_json_object_not_array_returns_empty_list(self):
        """Model returns a dict instead of a list."""
        result = reflect(
            agent="aetheria",
            turns=_turns(("user", "hi")),
            prior_note="",
            chat_fn=_chat_fn_returning_raw('{"text": "foo", "scope": "manner"}'),
        )
        assert result == []

    def test_empty_string_returns_empty_list(self):
        result = reflect(
            agent="aetheria",
            turns=_turns(("user", "hi")),
            prior_note="",
            chat_fn=_chat_fn_returning_raw(""),
        )
        assert result == []

    def test_partial_json_returns_empty_list(self):
        result = reflect(
            agent="aetheria",
            turns=_turns(("user", "hi")),
            prior_note="",
            chat_fn=_chat_fn_returning_raw("[{broken"),
        )
        assert result == []

    def test_model_returns_empty_array_returns_empty_list(self):
        result = reflect(
            agent="aetheria",
            turns=_turns(("user", "hi")),
            prior_note="",
            chat_fn=_chat_fn_returning([]),
        )
        assert result == []


# ─── Mixed array: good items survive, bad items skipped ──────────────────────

class TestMixedArray:
    """One good item + one bad item → good one parsed, bad one skipped."""

    def test_missing_text_field_skips_bad_item(self):
        payload = [
            # good item
            {
                "text": "Jon dislikes filler phrases.",
                "scope": "manner",
                "citations": ["t1"],
                "jon_originated": True,
            },
            # bad item: missing 'text'
            {
                "scope": "manner",
                "citations": ["t2"],
                "jon_originated": True,
            },
        ]
        result = reflect(
            agent="aetheria",
            turns=_turns(("user", "no filler please"), ("assistant", "ok")),
            prior_note="",
            chat_fn=_chat_fn_returning(payload),
        )
        assert len(result) == 1
        assert result[0].text == "Jon dislikes filler phrases."

    def test_missing_scope_field_skips_bad_item(self):
        payload = [
            {
                "text": "Good observation.",
                "scope": "manner",
                "citations": ["t1"],
                "jon_originated": True,
            },
            {
                "text": "Bad observation — no scope.",
                "citations": ["t2"],
                "jon_originated": True,
            },
        ]
        result = reflect(
            agent="aetheria",
            turns=_turns(("user", "test")),
            prior_note="",
            chat_fn=_chat_fn_returning(payload),
        )
        assert len(result) == 1
        assert result[0].text == "Good observation."

    def test_missing_citations_field_skips_bad_item(self):
        payload = [
            {
                "text": "Good observation.",
                "scope": "value",
                "citations": ["t1"],
                "jon_originated": True,
            },
            {
                "text": "Bad — no citations key at all.",
                "scope": "manner",
                "jon_originated": True,
            },
        ]
        result = reflect(
            agent="aetheria",
            turns=_turns(("user", "test")),
            prior_note="",
            chat_fn=_chat_fn_returning(payload),
        )
        assert len(result) == 1
        assert result[0].scope == "value"

    def test_missing_jon_originated_skips_bad_item(self):
        payload = [
            {
                "text": "Good.",
                "scope": "manner",
                "citations": ["t1"],
                "jon_originated": True,
            },
            {
                "text": "Bad — no jon_originated key.",
                "scope": "manner",
                "citations": ["t2"],
                # jon_originated missing
            },
        ]
        result = reflect(
            agent="aetheria",
            turns=_turns(("user", "test")),
            prior_note="",
            chat_fn=_chat_fn_returning(payload),
        )
        assert len(result) == 1
        assert result[0].text == "Good."

    def test_non_dict_item_in_array_skips_it(self):
        """An item that is not a dict (e.g. a string) is skipped."""
        payload = [
            "this is a string not a dict",
            {
                "text": "Valid.",
                "scope": "unsure",
                "citations": ["t1"],
                "jon_originated": False,
            },
        ]
        result = reflect(
            agent="aetheria",
            turns=_turns(("user", "test")),
            prior_note="",
            chat_fn=_chat_fn_returning(payload),
        )
        assert len(result) == 1
        assert result[0].text == "Valid."

    def test_all_items_bad_returns_empty_list(self):
        payload = [
            {"scope": "manner", "citations": ["t1"], "jon_originated": True},
            {"text": "foo", "citations": ["t2"]},  # missing scope + jon_originated
        ]
        result = reflect(
            agent="aetheria",
            turns=_turns(("user", "test")),
            prior_note="",
            chat_fn=_chat_fn_returning(payload),
        )
        assert result == []


# ─── Prompt contains key context (smoke-level — not exhaustive) ──────────────

class TestPromptContent:
    """The prompt passed to chat_fn includes the turn content and prior_note."""

    def test_turn_content_reaches_prompt(self):
        """Turn text appears somewhere in the user prompt sent to chat_fn."""
        captured = {}

        def _capture_fn(system: str, user: str) -> str:
            captured["system"] = system
            captured["user"] = user
            return "[]"

        turns = _turns(
            ("user", "UNIQUE_MARKER_FOR_TURN_CONTENT"),
            ("assistant", "response"),
        )
        reflect(
            agent="aetheria",
            turns=turns,
            prior_note="",
            chat_fn=_capture_fn,
        )
        full_prompt = captured.get("system", "") + captured.get("user", "")
        assert "UNIQUE_MARKER_FOR_TURN_CONTENT" in full_prompt

    def test_prior_note_reaches_prompt(self):
        """prior_note appears somewhere in the prompt sent to chat_fn."""
        captured = {}

        def _capture_fn(system: str, user: str) -> str:
            captured["system"] = system
            captured["user"] = user
            return "[]"

        turns = _turns(("user", "hello"))
        reflect(
            agent="aetheria",
            turns=turns,
            prior_note="PRIOR_NOTE_UNIQUE_TOKEN",
            chat_fn=_capture_fn,
        )
        full_prompt = captured.get("system", "") + captured.get("user", "")
        assert "PRIOR_NOTE_UNIQUE_TOKEN" in full_prompt

    def test_agent_name_reaches_prompt(self):
        """Agent name appears somewhere in the prompt."""
        captured = {}

        def _capture_fn(system: str, user: str) -> str:
            captured["system"] = system
            captured["user"] = user
            return "[]"

        reflect(
            agent="AGENT_NAME_TOKEN",
            turns=_turns(("user", "hi")),
            prior_note="",
            chat_fn=_capture_fn,
        )
        full_prompt = captured.get("system", "") + captured.get("user", "")
        assert "AGENT_NAME_TOKEN" in full_prompt
