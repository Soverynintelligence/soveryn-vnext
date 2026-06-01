"""Tests for streaming tool dispatch in AgentLoop.process_message_stream.

Mirrors the sync-path tool-call iteration tests
(test_agent_loop_tool_loop.py) but exercises the streaming code path,
which is the one the UI actually uses (/chat_stream).

Phase shipped 2026-06-01 — see commit log for context.
"""

import json
import pytest

from soveryn.agents.loop import (
    AgentLoop, DoneEvent, ErrorEvent, TokenEvent, ToolCallEvent, ToolResultEvent,
)
from soveryn.inference.llama_server_client import StreamChunk
from soveryn.memory.conversation_store import ConversationStore
from soveryn.platform.tools.registry import ToolRegistry, ToolSpec


@pytest.fixture
def conv_store(tmp_path):
    return ConversationStore(tmp_path / "conv.db")


def _make_registry(handler, *, tool_name="echo", owner="aetheria"):
    """Build a registry with a single echo-style tool owned by `owner`."""
    registry = ToolRegistry(active_agents=("aetheria",), audit_hook=None)
    registry.register(ToolSpec(
        name=tool_name,
        owner=owner,
        schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
        handler=handler,
        description="echo tool",
    ))
    return registry


def _tool_call_delta(index, *, call_id=None, name=None, arg_chunk=None):
    """OpenAI-shape tool_call delta."""
    d: dict = {"index": index}
    if call_id is not None:
        d["id"] = call_id
        d["type"] = "function"
    if name is not None or arg_chunk is not None:
        fn: dict = {}
        if name is not None:
            fn["name"] = name
        if arg_chunk is not None:
            fn["arguments"] = arg_chunk
        d["function"] = fn
    return d


class _MultiRoundStream:
    """stream_fn that returns a fresh set of chunks per invocation.

    Round N's chunks come from `rounds[N]`. Tracks every call's request so tests
    can assert on multi-turn message assembly.
    """
    def __init__(self, rounds):
        self.rounds = list(rounds)
        self.calls = []

    def __call__(self, request, server, timeout=120.0):
        self.calls.append({"request": request, "server": server, "timeout": timeout})
        if not self.rounds:
            raise AssertionError("_MultiRoundStream ran out of scripted rounds")
        round_chunks = self.rounds.pop(0)
        def _gen():
            for c in round_chunks:
                yield c
        return _gen()


# ─── Happy path ──────────────────────────────────────────────────────────────

def test_streaming_single_tool_call_dispatched_and_threaded_back(conv_store):
    """Round 1 emits a tool_call (no content). We invoke. Round 2 streams the answer."""
    registry = _make_registry(lambda args: {"echoed": args["text"]})
    stream = _MultiRoundStream([
        # Round 1: tool_call deltas, no content, finish=tool_calls
        [
            StreamChunk(delta="", finish_reason=None,
                        tool_calls_delta=[_tool_call_delta(0, call_id="c1", name="echo")],
                        usage=None, raw={}),
            StreamChunk(delta="", finish_reason=None,
                        tool_calls_delta=[_tool_call_delta(0, arg_chunk='{"text": "hi"}')],
                        usage=None, raw={}),
            StreamChunk(delta="", finish_reason="tool_calls", tool_calls_delta=None,
                        usage=None, raw={}),
        ],
        # Round 2: streaming visible answer
        [
            StreamChunk(delta="echo result was ",
                        finish_reason=None, tool_calls_delta=None, usage=None, raw={}),
            StreamChunk(delta="hi", finish_reason=None,
                        tool_calls_delta=None, usage=None, raw={}),
            StreamChunk(delta="", finish_reason="stop",
                        tool_calls_delta=None, usage={"total_tokens": 4}, raw={}),
        ],
    ])

    sid = conv_store.new_session("aetheria")
    loop = AgentLoop("aetheria", conv_store, stream_fn=stream,
                    tool_registry=registry, max_tool_rounds=4)
    events = list(loop.process_message_stream(sid, "use the echo tool"))

    # ToolCallEvent + ToolResultEvent both fire between rounds
    tool_calls = [e for e in events if isinstance(e, ToolCallEvent)]
    tool_results = [e for e in events if isinstance(e, ToolResultEvent)]
    assert len(tool_calls) == 1
    assert tool_calls[0].name == "echo"
    assert tool_calls[0].call_id == "c1"
    assert tool_calls[0].args == '{"text": "hi"}'
    assert len(tool_results) == 1
    assert tool_results[0].call_id == "c1"
    assert json.loads(tool_results[0].content) == {"echoed": "hi"}

    # Token deltas stream the round-2 answer
    deltas = [e.delta for e in events if isinstance(e, TokenEvent)]
    assert "".join(deltas) == "echo result was hi"

    # Final DoneEvent carries the visible answer; tool_calls scrubbed from DoneEvent
    # because dispatch already happened (they're plumbing, not the final turn).
    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert done.content == "echo result was hi"
    assert done.finish_reason == "stop"
    assert done.tool_calls is None

    # Assistant turn saved with the visible content only
    history = conv_store.load_history(sid)
    roles = [t.role for t in history]
    assert roles == ["user", "assistant"]
    assert history[1].content == "echo result was hi"

    # Both rounds happened
    assert len(stream.calls) == 2
    # Round-2 request includes the assistant-with-tool_calls + tool result messages
    round2_msgs = stream.calls[1]["request"].messages
    assistant_with_tc = [m for m in round2_msgs if m.role == "assistant"]
    assert len(assistant_with_tc) == 1
    assert assistant_with_tc[0].tool_calls is not None
    tool_msgs = [m for m in round2_msgs if m.role == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0].tool_call_id == "c1"
    assert json.loads(tool_msgs[0].content) == {"echoed": "hi"}


def test_streaming_tools_field_present_in_chat_request_when_registry_present(conv_store):
    """The streaming request must carry tools=schemas when registry has tools,
    or the model can never emit a tool_call. This was the upstream bug that
    blocked tool use through the UI prior to this phase."""
    registry = _make_registry(lambda args: {"echoed": args["text"]})
    stream = _MultiRoundStream([
        [StreamChunk(delta="ok", finish_reason="stop",
                     tool_calls_delta=None, usage=None, raw={})],
    ])
    sid = conv_store.new_session("aetheria")
    loop = AgentLoop("aetheria", conv_store, stream_fn=stream,
                    tool_registry=registry)
    list(loop.process_message_stream(sid, "hi"))
    req = stream.calls[0]["request"]
    assert req.tools is not None
    tool_names = [t["function"]["name"] for t in req.tools]
    assert "echo" in tool_names


def test_streaming_max_tool_rounds_cap_terminates(conv_store):
    """If the model keeps requesting tools forever, we cap at max_tool_rounds
    and surface a 'tool_round_limit' finish reason."""
    registry = _make_registry(lambda args: {"echoed": args["text"]})

    def _tool_call_round():
        return [
            StreamChunk(delta="", finish_reason=None,
                        tool_calls_delta=[_tool_call_delta(0, call_id="c", name="echo")],
                        usage=None, raw={}),
            StreamChunk(delta="", finish_reason=None,
                        tool_calls_delta=[_tool_call_delta(0, arg_chunk='{"text": "x"}')],
                        usage=None, raw={}),
            StreamChunk(delta="loop", finish_reason="tool_calls",
                        tool_calls_delta=None, usage=None, raw={}),
        ]

    # max_tool_rounds=2 → rounds 0 and 1 dispatch; round 2 hits the cap.
    stream = _MultiRoundStream([_tool_call_round() for _ in range(3)])
    sid = conv_store.new_session("aetheria")
    loop = AgentLoop("aetheria", conv_store, stream_fn=stream,
                    tool_registry=registry, max_tool_rounds=2)
    events = list(loop.process_message_stream(sid, "spin"))

    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert done.finish_reason == "tool_round_limit"
    # The round-3 content "loop" is preserved when the cap fires (not lost).
    assert "loop" in done.content


def test_streaming_tool_handler_exception_becomes_tool_result_not_crash(conv_store):
    """A tool handler that raises mid-dispatch should NOT crash the whole stream;
    its failure becomes a tool_result payload the model can react to. Mirrors
    the sync-path contract from test_agent_loop_tool_loop.py."""
    def _boom(_args):
        raise RuntimeError("simulated tool failure")
    registry = _make_registry(_boom)

    stream = _MultiRoundStream([
        [
            StreamChunk(delta="", finish_reason=None,
                        tool_calls_delta=[_tool_call_delta(0, call_id="c1", name="echo")],
                        usage=None, raw={}),
            StreamChunk(delta="", finish_reason=None,
                        tool_calls_delta=[_tool_call_delta(0, arg_chunk='{"text": "x"}')],
                        usage=None, raw={}),
            StreamChunk(delta="", finish_reason="tool_calls",
                        tool_calls_delta=None, usage=None, raw={}),
        ],
        [
            StreamChunk(delta="handled error", finish_reason="stop",
                        tool_calls_delta=None, usage=None, raw={}),
        ],
    ])
    sid = conv_store.new_session("aetheria")
    loop = AgentLoop("aetheria", conv_store, stream_fn=stream, tool_registry=registry)
    events = list(loop.process_message_stream(sid, "go"))

    tool_results = [e for e in events if isinstance(e, ToolResultEvent)]
    assert len(tool_results) == 1
    payload = json.loads(tool_results[0].content)
    assert payload["error"] == "RuntimeError"
    assert "simulated tool failure" in payload["message"]
    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert done.content == "handled error"


def test_streaming_no_tool_registry_passes_through_unchanged(conv_store):
    """Without a tool_registry, streaming surfaces tool_calls in DoneEvent
    instead of dispatching. Old contract preserved for callers that handle
    dispatch externally (test harnesses, future custom clients)."""
    stream = _MultiRoundStream([
        [
            StreamChunk(delta="", finish_reason=None,
                        tool_calls_delta=[_tool_call_delta(0, call_id="c", name="anything",
                                                          arg_chunk='{}')],
                        usage=None, raw={}),
            StreamChunk(delta="", finish_reason="tool_calls",
                        tool_calls_delta=None, usage=None, raw={}),
        ],
    ])
    sid = conv_store.new_session("aetheria")
    loop = AgentLoop("aetheria", conv_store, stream_fn=stream)  # no tool_registry
    events = list(loop.process_message_stream(sid, "go"))
    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert done.tool_calls is not None
    assert len(done.tool_calls) == 1
    assert done.finish_reason == "tool_calls"
    # No dispatch events fired (no registry, no invocation)
    assert not any(isinstance(e, ToolCallEvent) for e in events)
    assert not any(isinstance(e, ToolResultEvent) for e in events)
