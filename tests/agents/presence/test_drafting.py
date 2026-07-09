"""Tests for draft_for_candidate — Aetheria drafting with mandatory provenance."""

from soveryn.agents.presence.drafting import draft_for_candidate, Draft
from soveryn.agents.presence.candidate_store import Candidate

C = Candidate("1", "a", "local LLM honesty?", "u", "reply", 3.0, "pending", "t")


def test_draft_carries_provenance():
    fn = lambda p: '{"post":"Grounded honesty beats confident guessing.","based_on":"our confab measurements","skip":false}'
    d = draft_for_candidate(C, fn)
    assert isinstance(d, Draft) and d.based_on == "our confab measurements"
    assert d.in_reply_to == "1" and d.kind == "reply"


def test_skip_returns_none():
    fn = lambda p: '{"post":"","based_on":"","skip":true}'
    assert draft_for_candidate(C, fn) is None


def test_missing_provenance_flagged_not_dropped():
    fn = lambda p: '{"post":"a claim","based_on":"","skip":false}'
    d = draft_for_candidate(C, fn)
    assert d is not None and d.based_on == "(none stated)"


def test_non_json_return_treated_as_skip():
    fn = lambda p: "sure, here's a great tweet: local LLMs are honest!"
    assert draft_for_candidate(C, fn) is None


def test_empty_post_treated_as_skip_even_if_skip_false():
    fn = lambda p: '{"post":"","based_on":"something","skip":false}'
    assert draft_for_candidate(C, fn) is None


def test_topic_kind_has_no_in_reply_to():
    topic_candidate = Candidate("2", "b", "on-device inference", "u", "topic", 2.0, "pending", "t")
    fn = lambda p: '{"post":"On-device inference is the sovereignty lever.","based_on":"our hardware roadmap","skip":false}'
    d = draft_for_candidate(topic_candidate, fn)
    assert d is not None and d.in_reply_to is None and d.kind == "topic"


def test_mention_kind_carries_in_reply_to():
    mention_candidate = Candidate("3", "c", "@Soveryn_AI thoughts?", "u", "mention", 4.0, "pending", "t")
    fn = lambda p: '{"post":"Happy to share our approach.","based_on":"our published measurements","skip":false}'
    d = draft_for_candidate(mention_candidate, fn)
    assert d is not None and d.in_reply_to == "3" and d.kind == "mention"


def test_draft_fn_receives_a_prompt_string():
    captured = {}

    def fn(prompt):
        captured["prompt"] = prompt
        return '{"post":"ok","based_on":"x","skip":false}'

    draft_for_candidate(C, fn)
    assert isinstance(captured["prompt"], str) and C.text in captured["prompt"]
