"""AgentLoop ↔ SteeringRack integration — circuit breaker stops a
Harness-1-style death loop by short-circuiting repeated empty searches.

The breaker is unit-tested in test_platform_steering_rack.py — here we
verify that AgentLoop:
 - dispatches normally when the breaker is unset or untripped
 - threads session_id into _tool_result_message
 - returns the synthetic steering_rack_open result when the breaker trips
 - the trip surfaces in BlackBox trajectory (same JSON the model sees)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from soveryn.agents.loop import AgentLoop
from soveryn.inference.llama_server_client import ChatResponse
from soveryn.memory.conversation_store import ConversationStore
from soveryn.platform.black_box import BlackBox
from soveryn.platform.steering_rack import SteeringRack
from soveryn.platform.tools.registry import ToolRegistry, ToolSpec


@pytest.fixture
def conv_store(tmp_path: Path) -> ConversationStore:
    return ConversationStore(tmp_path / "conv.db")


def _empty_search_handler(_args: dict) -> dict:
    """Always returns an empty result — drives the breaker."""
    return {"engine": "test", "results": []}


def _registry_with_search() -> ToolRegistry:
    reg = ToolRegistry(active_agents=("aetheria",), audit_hook=None)
    reg.register(ToolSpec(
        name="web_search",
        owner="aetheria",
        schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        handler=_empty_search_handler,
        description="search tool",
    ))
    return reg


class _ScriptedChat:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def __call__(self, request, server, timeout=60.0):
        self.calls.append({"request": request, "server": server, "timeout": timeout})
        return self._responses.pop(0)


def _tool_call(call_id: str, query: str) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": "web_search", "arguments": json.dumps({"query": query})},
    }


def _wants_search_response(call_id: str, query: str) -> ChatResponse:
    return ChatResponse(
        content="",
        finish_reason="tool_calls",
        tool_calls=[_tool_call(call_id, query)],
        usage=None,
        raw={},
    )


def _final_response(text: str) -> ChatResponse:
    return ChatResponse(
        content=text, finish_reason="stop", tool_calls=None,
        usage={"total_tokens": 1}, raw={},
    )


# ─── Breaker trips after 3 near-identical empty searches ────────────────────

def test_three_paraphrased_empty_searches_trip_the_breaker(
    conv_store: ConversationStore,
):
    """The Harness-1 failure shape: 3 paraphrased empty searches → 4th
    call short-circuits to steering_rack_open before the handler runs."""
    rack = SteeringRack(sim_threshold=0.6, consecutive_empties_threshold=3)
    scripted = _ScriptedChat([
        _wants_search_response("c1", "SOVERYN Scotty renamed from Tinker 2026-05-02"),
        _wants_search_response("c2", "SOVERYN Tinker renamed Scotty 2026-05-02"),
        _wants_search_response("c3", "Scotty renamed from Tinker 2026-05-02 SOVERYN engineer"),
        _wants_search_response("c4", "Scotty Tinker rename 2026 05 02 SOVERYN engineering"),
        _final_response("Couldn't find it; I'll stop looking."),
    ])
    loop = AgentLoop(
        "aetheria", conv_store,
        chat_fn=scripted,
        tool_registry=_registry_with_search(),
        max_tool_rounds=10,
        steering_rack=rack,
    )
    sid = conv_store.new_session("aetheria")
    loop.process_message(sid, "find the rename memo")

    # The 4th tool dispatch must have been short-circuited. The request sent
    # to chat after round 3 carries a tool message with steering_rack_open.
    last_request = scripted.calls[-1]["request"]
    tool_msgs = [m for m in last_request.messages if m.role == "tool"]
    last_tool_content = tool_msgs[-1].content
    decoded = json.loads(last_tool_content)
    assert decoded["error"] == "steering_rack_open", (
        f"4th tool call should have short-circuited; got: {last_tool_content}"
    )


# ─── Distinct queries do NOT trip the breaker ────────────────────────────────

def test_distinct_empty_searches_do_not_trip_the_breaker(
    conv_store: ConversationStore,
):
    """3 totally different empty queries means the agent is exploring,
    not looping. Breaker must NOT trip."""
    rack = SteeringRack()
    scripted = _ScriptedChat([
        _wants_search_response("c1", "alpha beta gamma"),
        _wants_search_response("c2", "delta epsilon zeta"),
        _wants_search_response("c3", "omega xi mu"),
        _final_response("Nothing matched."),
    ])
    loop = AgentLoop(
        "aetheria", conv_store,
        chat_fn=scripted,
        tool_registry=_registry_with_search(),
        max_tool_rounds=10,
        steering_rack=rack,
    )
    sid = conv_store.new_session("aetheria")
    loop.process_message(sid, "exploratory hunt")

    # All 3 tool messages must be real search results, NOT synthetic errors
    for call in scripted.calls[1:]:  # skip the initial dispatch
        tool_msgs = [m for m in call["request"].messages if m.role == "tool"]
        for tm in tool_msgs:
            decoded = json.loads(tm.content)
            assert decoded.get("error") != "steering_rack_open", (
                f"breaker false-tripped on distinct queries: {tm.content}"
            )


# ─── Trip lands in Black Box ─────────────────────────────────────────────────

def test_steering_rack_trip_lands_in_black_box(
    conv_store: ConversationStore,
    tmp_path: Path,
):
    """When the breaker trips, the synthetic error result lives in the
    Black Box observation slot — audit trail of every actual trip."""
    rack = SteeringRack(sim_threshold=0.6, consecutive_empties_threshold=3)
    bb = BlackBox(tmp_path / "bb")
    scripted = _ScriptedChat([
        _wants_search_response("c1", "scotty tinker rename memo"),
        _wants_search_response("c2", "tinker scotty rename memo"),
        _wants_search_response("c3", "rename memo tinker scotty"),
        _wants_search_response("c4", "memo rename scotty tinker"),
        _final_response("stopped per the breaker hint"),
    ])
    loop = AgentLoop(
        "aetheria", conv_store,
        chat_fn=scripted,
        tool_registry=_registry_with_search(),
        max_tool_rounds=10,
        black_box=bb,
        steering_rack=rack,
    )
    sid = conv_store.new_session("aetheria")
    loop.process_message(sid, "find the memo")

    bb_path = tmp_path / "bb" / "aetheria" / f"{sid}.jsonl"
    rows = [json.loads(line) for line in bb_path.read_text().splitlines() if line.strip()]
    assert len(rows) == 1
    row = rows[0]
    # The 4th observation entry (round_index 3) must carry the trip
    aandos = row["actions_and_observations"]
    observations = [a for a in aandos if a["type"] == "observation"]
    assert len(observations) == 4
    last_obs = observations[-1]
    last_result = last_obs["results"][0]
    decoded = json.loads(last_result["content"])
    assert decoded["error"] == "steering_rack_open"
    # And the recorder marks it as a tool_error since the result has an
    # error field — useful for grepping "how many trips per session"
    assert row["telemetry"]["tool_error_count"] >= 1


# ─── No SteeringRack → identical behavior ────────────────────────────────────

def test_without_steering_rack_loop_runs_normally(
    conv_store: ConversationStore,
):
    """steering_rack=None: AgentLoop behaves exactly like pre-breaker.
    Optional-dependency contract."""
    scripted = _ScriptedChat([
        _wants_search_response("c1", "x"),
        _final_response("hi"),
    ])
    loop = AgentLoop(
        "aetheria", conv_store,
        chat_fn=scripted,
        tool_registry=_registry_with_search(),
        max_tool_rounds=4,
        steering_rack=None,
    )
    sid = conv_store.new_session("aetheria")
    result = loop.process_message(sid, "search please")
    assert result.content == "hi"
