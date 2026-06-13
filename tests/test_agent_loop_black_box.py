"""AgentLoop ↔ BlackBox integration — recorder is fed correctly from both
the sync and streaming tool-loop sites, and failure paths still emit a
record so the audit trail covers misses.

Two paths under test:
 - process_message            (sync)
 - process_message_stream     (streaming)

The recorder itself is unit-tested in test_platform_black_box.py — here
we only assert that the wiring inside loop.py passes the right shape.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from soveryn.agents.loop import AgentLoop, AgentLoopError
from soveryn.inference.llama_server_client import ChatResponse
from soveryn.memory.conversation_store import ConversationStore
from soveryn.platform.black_box import BlackBox
from soveryn.platform.tools.registry import ToolRegistry, ToolSpec


@pytest.fixture
def conv_store(tmp_path: Path) -> ConversationStore:
    return ConversationStore(tmp_path / "conv.db")


@pytest.fixture
def black_box(tmp_path: Path) -> BlackBox:
    return BlackBox(tmp_path / "bb")


def _echo_tool(_agent: str, args: dict) -> dict:
    return {"echoed": args.get("text", "")}


def _registry_with_echo() -> ToolRegistry:
    reg = ToolRegistry(active_agents=("aetheria",), audit_hook=None)
    reg.register(
        ToolSpec(
            name="echo",
            owner="aetheria",
            schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
                "additionalProperties": False,
            },
            handler=lambda args: {"echoed": args.get("text", "")},
            description="echo back the text",
        )
    )
    return reg


class _ScriptedChat:
    """chat_fn that returns a pre-baked sequence of ChatResponses.
    Each call consumes the next response in the script."""

    def __init__(self, responses: list[ChatResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def __call__(self, request, server, timeout=60.0):
        self.calls.append({"request": request, "server": server, "timeout": timeout})
        if not self._responses:
            raise AssertionError("scripted chat exhausted unexpectedly")
        return self._responses.pop(0)


def _tool_call(call_id: str, name: str, args: dict) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


def _read_jsonl(bb_root: Path, agent: str, session_id: str) -> list[dict]:
    path = bb_root / agent / f"{session_id}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ─── No tools called → no JSONL line ──────────────────────────────────────────

def test_sync_turn_with_no_tool_calls_writes_no_record(
    conv_store: ConversationStore,
    black_box: BlackBox,
    tmp_path: Path,
):
    """A plain answer-in-one-shot turn must NOT produce a black-box record.
    The audit log is for tool-using turns only."""
    scripted = _ScriptedChat([
        ChatResponse(content="hello back", finish_reason="stop", tool_calls=None,
                     usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                     raw={}),
    ])
    loop = AgentLoop(
        "aetheria", conv_store, chat_fn=scripted,
        black_box=black_box,
    )
    sid = conv_store.new_session("aetheria")
    loop.process_message(sid, "hi")
    # No JSONL was written
    bb_root = tmp_path / "bb"
    if bb_root.exists():
        produced = list(bb_root.rglob("*.jsonl"))
        assert produced == [], f"unexpected JSONL files: {produced}"


# ─── Successful tool-loop turn → one record with action+observation ──────────

def test_sync_turn_with_tool_calls_writes_full_trajectory(
    conv_store: ConversationStore,
    black_box: BlackBox,
    tmp_path: Path,
):
    """Round 1: model emits one tool call. Round 2: model finalises with
    visible content. JSONL row has both action and observation."""
    scripted = _ScriptedChat([
        ChatResponse(
            content="",
            finish_reason="tool_calls",
            tool_calls=[_tool_call("c1", "echo", {"text": "ping"})],
            usage=None,
            raw={},
        ),
        ChatResponse(
            content="I echoed it.", finish_reason="stop", tool_calls=None,
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            raw={},
        ),
    ])
    loop = AgentLoop(
        "aetheria", conv_store, chat_fn=scripted,
        tool_registry=_registry_with_echo(),
        black_box=black_box,
    )
    sid = conv_store.new_session("aetheria")
    loop.process_message(sid, "echo ping please")

    rows = _read_jsonl(tmp_path / "bb", "aetheria", sid)
    assert len(rows) == 1
    row = rows[0]
    assert row["session_id"] == sid
    assert row["agent"] == "aetheria"
    assert row["user_message"] == "echo ping please"
    assert row["final_content"] == "I echoed it."
    assert row["finish_reason"] == "stop"
    # action + observation in order
    aandos = row["actions_and_observations"]
    assert len(aandos) == 2
    assert aandos[0]["type"] == "action"
    assert aandos[0]["tool_calls"][0]["name"] == "echo"
    assert aandos[1]["type"] == "observation"
    assert "echoed" in aandos[1]["results"][0]["content"]
    assert aandos[1]["results"][0]["error"] is None
    # Telemetry block — the explicit finish_reason Jon called out
    tele = row["telemetry"]
    assert tele["num_rounds"] == 1
    assert tele["tool_calls"] == {"echo": 1}
    assert tele["tool_error_count"] == 0
    assert tele["tool_round_limit_hit"] is False
    assert tele["finish_reason"] == "stop"


# ─── tool_round_limit hit → record persists with the failure mode ────────────

def test_sync_tool_round_limit_records_failure_mode(
    conv_store: ConversationStore,
    black_box: BlackBox,
    tmp_path: Path,
):
    """Jon's load-bearing case: model keeps requesting tools, hits the cap,
    raises AgentLoopError. The trajectory + finish_reason must still land
    in the JSONL so the failure is greppable."""
    cap_reaching_call = _tool_call("c", "echo", {"text": "x"})
    # max_tool_rounds=2 + cap_response after the loop short-circuits.
    # Round 0: model wants tools → dispatched
    # Round 1: model still wants tools → dispatched
    # Round 2: model STILL wants tools → loop short-circuits with tool_round_limit
    scripted = _ScriptedChat([
        ChatResponse(content="", finish_reason="tool_calls",
                     tool_calls=[cap_reaching_call], usage=None, raw={}),
        ChatResponse(content="", finish_reason="tool_calls",
                     tool_calls=[cap_reaching_call], usage=None, raw={}),
        ChatResponse(content="", finish_reason="tool_calls",
                     tool_calls=[cap_reaching_call], usage=None, raw={}),
    ])
    loop = AgentLoop(
        "aetheria", conv_store, chat_fn=scripted,
        tool_registry=_registry_with_echo(),
        max_tool_rounds=2,
        black_box=black_box,
    )
    sid = conv_store.new_session("aetheria")
    with pytest.raises(AgentLoopError, match="tool_round_limit"):
        loop.process_message(sid, "go forever")

    rows = _read_jsonl(tmp_path / "bb", "aetheria", sid)
    assert len(rows) == 1
    row = rows[0]
    assert row["finish_reason"] == "tool_round_limit"
    assert row["telemetry"]["tool_round_limit_hit"] is True
    assert row["telemetry"]["finish_reason"] == "tool_round_limit"
    # Two rounds were executed (0 and 1) before the cap fired on round 2.
    assert row["telemetry"]["num_rounds"] == 2


# ─── empty_generation after tools → still recorded ───────────────────────────

def test_sync_empty_generation_after_tool_records_failure(
    conv_store: ConversationStore,
    black_box: BlackBox,
    tmp_path: Path,
):
    """Model called one tool, then produced empty content with no tool_calls
    — AgentLoopError fires. Record must still land with finish_reason
    'empty_generation' (Jon: explicit failure modes are the whole point)."""
    scripted = _ScriptedChat([
        ChatResponse(content="", finish_reason="tool_calls",
                     tool_calls=[_tool_call("c1", "echo", {"text": "x"})],
                     usage=None, raw={}),
        ChatResponse(content="", finish_reason="stop", tool_calls=None,
                     usage=None, raw={}),
    ])
    loop = AgentLoop(
        "aetheria", conv_store, chat_fn=scripted,
        tool_registry=_registry_with_echo(),
        black_box=black_box,
    )
    sid = conv_store.new_session("aetheria")
    with pytest.raises(AgentLoopError, match="empty_generation"):
        loop.process_message(sid, "call echo")
    rows = _read_jsonl(tmp_path / "bb", "aetheria", sid)
    assert len(rows) == 1
    assert rows[0]["finish_reason"] == "empty_generation"
    assert rows[0]["telemetry"]["finish_reason"] == "empty_generation"


# ─── black_box=None → no recorder, no writes, no failures ────────────────────

def test_sync_no_black_box_runs_normally(
    conv_store: ConversationStore,
    tmp_path: Path,
):
    """AgentLoop must work identically when black_box=None — the optional
    dependency contract."""
    scripted = _ScriptedChat([
        ChatResponse(content="hi", finish_reason="stop", tool_calls=None,
                     usage=None, raw={}),
    ])
    loop = AgentLoop("aetheria", conv_store, chat_fn=scripted, black_box=None)
    sid = conv_store.new_session("aetheria")
    result = loop.process_message(sid, "hello")
    assert result.content == "hi"


# ─── Streaming path tests ─────────────────────────────────────────────────────

from soveryn.inference.llama_server_client import StreamChunk
from soveryn.agents.loop import DoneEvent, ErrorEvent


def _tool_call_delta(index, *, call_id=None, name=None, arg_chunk=None):
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


def test_stream_turn_with_tool_calls_writes_full_trajectory(
    conv_store: ConversationStore,
    black_box: BlackBox,
    tmp_path: Path,
):
    """Streaming path mirror of the sync trajectory test: one tool round
    followed by visible answer → JSONL row with both action and observation
    + telemetry block with finish_reason='stop'."""
    stream = _MultiRoundStream([
        # Round 1: tool_call deltas, no content, finish=tool_calls
        [
            StreamChunk(delta="", finish_reason=None,
                        tool_calls_delta=[_tool_call_delta(0, call_id="c1", name="echo")],
                        usage=None, raw={}),
            StreamChunk(delta="", finish_reason=None,
                        tool_calls_delta=[_tool_call_delta(0, arg_chunk='{"text":"ping"}')],
                        usage=None, raw={}),
            StreamChunk(delta="", finish_reason="tool_calls", tool_calls_delta=None,
                        usage=None, raw={}),
        ],
        # Round 2: visible answer
        [
            StreamChunk(delta="echo ", finish_reason=None,
                        tool_calls_delta=None, usage=None, raw={}),
            StreamChunk(delta="done", finish_reason=None,
                        tool_calls_delta=None, usage=None, raw={}),
            StreamChunk(delta="", finish_reason="stop",
                        tool_calls_delta=None, usage={"total_tokens": 4}, raw={}),
        ],
    ])
    loop = AgentLoop(
        "aetheria", conv_store, stream_fn=stream,
        tool_registry=_registry_with_echo(),
        max_tool_rounds=4,
        black_box=black_box,
    )
    sid = conv_store.new_session("aetheria")
    list(loop.process_message_stream(sid, "echo ping please"))

    rows = _read_jsonl(tmp_path / "bb", "aetheria", sid)
    assert len(rows) == 1
    row = rows[0]
    assert row["finish_reason"] == "stop"
    assert row["final_content"] == "echo done"
    aandos = row["actions_and_observations"]
    assert len(aandos) == 2
    assert aandos[0]["type"] == "action"
    assert aandos[0]["tool_calls"][0]["name"] == "echo"
    assert aandos[1]["type"] == "observation"
    assert "echoed" in aandos[1]["results"][0]["content"]
    assert row["telemetry"]["num_rounds"] == 1
    assert row["telemetry"]["tool_calls"] == {"echo": 1}
    assert row["telemetry"]["tool_round_limit_hit"] is False


def test_stream_no_tool_calls_writes_no_record(
    conv_store: ConversationStore,
    black_box: BlackBox,
    tmp_path: Path,
):
    """One-shot stream answer (no tools) → no JSONL."""
    stream = _MultiRoundStream([
        [
            StreamChunk(delta="hello", finish_reason=None,
                        tool_calls_delta=None, usage=None, raw={}),
            StreamChunk(delta="", finish_reason="stop",
                        tool_calls_delta=None, usage={"total_tokens": 1}, raw={}),
        ],
    ])
    loop = AgentLoop(
        "aetheria", conv_store, stream_fn=stream,
        black_box=black_box,
    )
    sid = conv_store.new_session("aetheria")
    list(loop.process_message_stream(sid, "hi"))
    bb_root = tmp_path / "bb"
    if bb_root.exists():
        assert list(bb_root.rglob("*.jsonl")) == []


def test_stream_tool_round_limit_records_failure_mode(
    conv_store: ConversationStore,
    black_box: BlackBox,
    tmp_path: Path,
):
    """Streaming: model keeps requesting tools, hits the cap. Record persists
    with finish_reason='tool_round_limit'."""
    def _persistent_call_round():
        return [
            StreamChunk(delta="", finish_reason=None,
                        tool_calls_delta=[_tool_call_delta(0, call_id="c", name="echo")],
                        usage=None, raw={}),
            StreamChunk(delta="", finish_reason=None,
                        tool_calls_delta=[_tool_call_delta(0, arg_chunk='{"text":"x"}')],
                        usage=None, raw={}),
            StreamChunk(delta="", finish_reason="tool_calls", tool_calls_delta=None,
                        usage=None, raw={}),
        ]
    stream = _MultiRoundStream([
        _persistent_call_round(),
        _persistent_call_round(),
        _persistent_call_round(),
    ])
    loop = AgentLoop(
        "aetheria", conv_store, stream_fn=stream,
        tool_registry=_registry_with_echo(),
        max_tool_rounds=2,
        black_box=black_box,
    )
    sid = conv_store.new_session("aetheria")
    events = list(loop.process_message_stream(sid, "go forever"))
    # The stream surfaces the error event
    errors = [e for e in events if isinstance(e, ErrorEvent)]
    assert any(e.code == "tool_round_limit" for e in errors)

    rows = _read_jsonl(tmp_path / "bb", "aetheria", sid)
    assert len(rows) == 1
    assert rows[0]["finish_reason"] == "tool_round_limit"
    assert rows[0]["telemetry"]["tool_round_limit_hit"] is True
    assert rows[0]["telemetry"]["finish_reason"] == "tool_round_limit"
