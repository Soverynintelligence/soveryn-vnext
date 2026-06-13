"""SteeringRack unit tests — pure module, no AgentLoop.

The integration with AgentLoop is tested separately in
test_agent_loop_steering_rack.py. This file exercises the breaker API:
detection rules, similarity threshold, empty detection, stickiness.
"""
from __future__ import annotations

import json

import pytest

from soveryn.platform.steering_rack import (
    SteeringRack,
    _jaccard,
    _tokenize,
    is_empty_result,
)


# ─── Helpers / tokenization ───────────────────────────────────────────────────

def test_tokenize_lowercases_and_strips_punctuation():
    assert _tokenize("SOVERYN Scotty renamed from Tinker 2026-05-02") == frozenset(
        {"soveryn", "scotty", "renamed", "from", "tinker", "2026", "05", "02"}
    )


def test_jaccard_identical_strings_is_one():
    a = _tokenize("alpha beta gamma")
    b = _tokenize("alpha beta gamma")
    assert _jaccard(a, b) == 1.0


def test_jaccard_disjoint_is_zero():
    a = _tokenize("alpha beta")
    b = _tokenize("gamma delta")
    assert _jaccard(a, b) == 0.0


def test_jaccard_paraphrase_matches_harness1_rephrase_threshold():
    """The 17-turn Harness-1 loop: queries paraphrased the same subclaim.
    Sample pair from the eval report — these MUST score >= 0.7 so the
    breaker would have caught them."""
    a = _tokenize("Scotty renamed from Tinker 2026-05-02 SOVERYN")
    b = _tokenize("SOVERYN Tinker renamed Scotty 2026-05-02")
    assert _jaccard(a, b) >= 0.7


# ─── Empty result detection ──────────────────────────────────────────────────

def test_is_empty_result_when_results_field_is_empty_list():
    payload = json.dumps({"engine": "searxng", "results": []})
    assert is_empty_result(payload) is True


def test_is_empty_result_when_nodes_field_is_empty_list():
    payload = json.dumps({"nodes": [], "count": 0})
    assert is_empty_result(payload) is True


def test_is_empty_result_falls_open_on_non_empty_collection():
    payload = json.dumps({"results": [{"snippet": "found"}]})
    assert is_empty_result(payload) is False


def test_is_empty_result_falls_open_on_unknown_shape():
    """If we don't recognise the result shape, don't trip — opaque tools
    must not false-trip the breaker."""
    payload = json.dumps({"echoed": "hello"})
    assert is_empty_result(payload) is False


def test_is_empty_result_falls_open_on_parse_failure():
    assert is_empty_result("not json") is False
    assert is_empty_result("") is False


def test_is_empty_result_does_not_count_tool_errors_as_empty():
    """A tool that errored is NOT an empty search. The breaker reacts to
    "I keep getting back zero results from real searches" — not to
    "the tool itself is broken." Different failure mode."""
    payload = json.dumps({"error": "RateLimit", "message": "429"})
    assert is_empty_result(payload) is False


# ─── Watched / unwatched tools ────────────────────────────────────────────────

def test_unwatched_tools_never_short_circuit():
    """A write tool like attic_write must never trip no matter how many
    times it's invoked."""
    rack = SteeringRack()
    for _ in range(10):
        tripped = rack.observe(
            session_id="s", tool_name="attic_write",
            args_text="anything",
            result_content=json.dumps({"results": []}),
        )
        assert tripped is False
    assert rack.should_short_circuit(session_id="s", tool_name="attic_write") is False


# ─── Trip rule (the core invariant) ───────────────────────────────────────────

def test_three_identical_empty_calls_to_same_tool_trips():
    """Identical args + 3 empty results in a row → trip."""
    rack = SteeringRack()
    empty = json.dumps({"results": []})
    args = json.dumps({"query": "thing"})
    assert rack.observe(session_id="s", tool_name="web_search",
                        args_text=args, result_content=empty) is False
    assert rack.observe(session_id="s", tool_name="web_search",
                        args_text=args, result_content=empty) is False
    assert rack.observe(session_id="s", tool_name="web_search",
                        args_text=args, result_content=empty) is True
    assert rack.should_short_circuit(session_id="s", tool_name="web_search") is True


def test_three_paraphrased_empties_trip_via_jaccard():
    """Harness-1 didn't paste the SAME query — she rephrased. The breaker
    must catch that via the Jaccard threshold."""
    rack = SteeringRack(sim_threshold=0.6)
    empty = json.dumps({"results": []})
    queries = [
        '{"query":"Scotty renamed from Tinker 2026-05-02 SOVERYN"}',
        '{"query":"SOVERYN Tinker renamed Scotty 2026-05-02"}',
        '{"query":"SOVERYN Scotty renamed from Tinker 2026-05-02 engineering agent"}',
    ]
    results = [
        rack.observe(session_id="s", tool_name="web_search",
                     args_text=q, result_content=empty)
        for q in queries
    ]
    assert results[-1] is True


def test_dissimilar_queries_do_not_trip_even_when_all_empty():
    """Three empty results from three TOTALLY different queries is not a
    death loop — the agent is genuinely exploring. Don't trip."""
    rack = SteeringRack()
    empty = json.dumps({"results": []})
    queries = [
        '{"query":"alpha beta gamma"}',
        '{"query":"delta epsilon"}',
        '{"query":"omega xi"}',
    ]
    last_tripped = False
    for q in queries:
        last_tripped = rack.observe(
            session_id="s", tool_name="web_search",
            args_text=q, result_content=empty,
        )
    assert last_tripped is False


def test_non_empty_call_in_the_window_breaks_the_streak():
    """Two empties + one hit + one empty must NOT trip — the agent is
    making progress, even if intermittent."""
    rack = SteeringRack()
    empty = json.dumps({"results": []})
    hit = json.dumps({"results": [{"snippet": "found"}]})
    args = json.dumps({"query": "x"})
    rack.observe(session_id="s", tool_name="web_search",
                 args_text=args, result_content=empty)
    rack.observe(session_id="s", tool_name="web_search",
                 args_text=args, result_content=empty)
    rack.observe(session_id="s", tool_name="web_search",
                 args_text=args, result_content=hit)
    tripped = rack.observe(session_id="s", tool_name="web_search",
                           args_text=args, result_content=empty)
    assert tripped is False


# ─── Stickiness ───────────────────────────────────────────────────────────────

def test_trip_is_sticky_until_process_restart():
    """Once tripped for (session, tool), every subsequent should_short_circuit
    returns True. The model has been told 3× — trying again is not useful."""
    rack = SteeringRack()
    empty = json.dumps({"results": []})
    args = json.dumps({"query": "x"})
    for _ in range(3):
        rack.observe(session_id="s", tool_name="web_search",
                     args_text=args, result_content=empty)
    assert rack.should_short_circuit(session_id="s", tool_name="web_search") is True
    # Even much later, breaker stays open
    for _ in range(5):
        rack.observe(session_id="s", tool_name="web_search",
                     args_text='{"query":"completely different now"}',
                     result_content=json.dumps({"results": [{"x": 1}]}))
    assert rack.should_short_circuit(session_id="s", tool_name="web_search") is True


# ─── Per-session, per-tool isolation ──────────────────────────────────────────

def test_trip_in_session_A_does_not_affect_session_B():
    """Each session has its own state. Aetheria getting stuck doesn't
    poison Vett's parallel investigation."""
    rack = SteeringRack()
    empty = json.dumps({"results": []})
    args = json.dumps({"query": "x"})
    for _ in range(3):
        rack.observe(session_id="A", tool_name="web_search",
                     args_text=args, result_content=empty)
    assert rack.should_short_circuit(session_id="A", tool_name="web_search") is True
    assert rack.should_short_circuit(session_id="B", tool_name="web_search") is False


def test_trip_in_web_search_does_not_affect_search_corpus():
    """Different tools tracked separately — if web is dry, the lattice
    might still find something."""
    rack = SteeringRack()
    empty = json.dumps({"results": []})
    args = json.dumps({"query": "x"})
    for _ in range(3):
        rack.observe(session_id="s", tool_name="web_search",
                     args_text=args, result_content=empty)
    assert rack.should_short_circuit(session_id="s", tool_name="web_search") is True
    assert rack.should_short_circuit(session_id="s", tool_name="search_corpus") is False


# ─── Synthetic error payload ──────────────────────────────────────────────────

def test_synthetic_error_carries_tool_name_and_hint():
    rack = SteeringRack()
    err = rack.synthetic_error(tool_name="web_search")
    assert err["error"] == "steering_rack_open"
    assert "web_search" in err["message"]
    assert "loop" in err["message"].lower()
    assert "different" in err["message"].lower()  # the steering hint
