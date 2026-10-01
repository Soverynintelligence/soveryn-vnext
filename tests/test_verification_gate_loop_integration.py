"""Integration: the verification gate hooked into the live AgentLoop.

Uses a scripted fake chat + a fake system_probe tool, no network, no shell.

Covered:
  - A Eve hardware-question turn with NO tools → gate holds the confab, forces
    a system_probe round → grounded answer; the confab never reaches the user.
  - A non-Eve turn is unaffected (identical to the pre-gate path).
  - Budget exhaustion → the honest floor.
  - Fail-open: a detector that raises never crashes the turn.
  - Streaming path: the confab is buffered and discarded on a hold.
"""

import json

import pytest

from soveryn.agents.loop import AgentLoop, DoneEvent, TokenEvent
from soveryn.memory.conversation_store import ConversationStore
from soveryn.platform.inference.llama_server_client import ChatResponse, StreamChunk
from soveryn.platform.tools.registry import ToolRegistry, ToolSpec
from soveryn.platform.verification.detector import RiskVerdict
from soveryn.platform.verification.gate import HONEST_FLOOR_ANSWER, VerificationGate


CONFAB = "the ROMED8-2T is Intel and the RTX 5000 has 32GB GDDR6"
GROUNDED = "Per system_probe: this box has 2 GPUs; I'll answer only from that."


@pytest.fixture
def conv_store(tmp_path):
    return ConversationStore(tmp_path / "conv.db")


class _ScriptedChat:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def __call__(self, request, server, timeout=60.0):
        self.calls.append(request)
        if not self._responses:
            raise AssertionError("ScriptedChat ran out of responses")
        return self._responses.pop(0)


def _tool_call(call_id, name, args_obj):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args_obj)},
    }


def _probe_registry(owner="eve"):
    registry = ToolRegistry(active_agents=("eve", "aetheria"), audit_hook=None)
    registry.register(ToolSpec(
        name="system_probe",
        owner=owner,
        schema={
            "type": "object",
            "properties": {"category": {"type": "string"}},
            "required": [],
            "additionalProperties": False,
        },
        handler=lambda args: {"category": "gpu", "fields": {"gpu_count": "2"}, "raw": "..."},
        description="probe",
    ))
    return registry


def test_eve_confab_is_held_and_forced_to_verify(conv_store):
    """The whole point: Eve drafts a confident hardware confab with zero tools;
    the gate holds it, injects the corrective, she calls system_probe, then
    answers from the probe. The confab never becomes the saved/returned answer."""
    fake = _ScriptedChat([
        # Round 1: confident confab, NO tool calls.
        ChatResponse(content=CONFAB, finish_reason="stop", tool_calls=None, usage={}, raw={}),
        # Round 2 (after corrective): she calls system_probe.
        ChatResponse(
            content="", finish_reason="tool_calls",
            tool_calls=(_tool_call("c1", "system_probe", {"category": "gpu"}),),
            usage={}, raw={},
        ),
        # Round 3: grounded answer from the probe.
        ChatResponse(content=GROUNDED, finish_reason="stop", tool_calls=None, usage={}, raw={}),
    ])
    gate = VerificationGate()  # Eve-only, budget 2
    sid = conv_store.new_session("eve")
    loop = AgentLoop(
        "eve", conv_store, chat_fn=fake, tool_registry=_probe_registry(),
        verification_gate=gate, soul_text="",
    )
    response = loop.process_message(sid, "will this RoCE cluster work on my rig?")

    assert response.content == GROUNDED
    assert response.content != CONFAB
    # A corrective system note was injected before round 2, and tool_choice
    # was forced so the model cannot keep narrating without a tool call.
    round2_msgs = fake.calls[1].messages
    assert any(
        m.role == "system"
        and (
            "tool" in (m.content or "").lower()
            or "verify" in (m.content or "").lower()
            or "NOW" in (m.content or "")
        )
        for m in round2_msgs
    ), "corrective note should be injected"
    assert fake.calls[1].tool_choice == "required"
    # The confab was never persisted as an assistant turn.
    history = conv_store.load_history(sid)
    assert all(CONFAB not in (t.content or "") for t in history)
    assert any(GROUNDED in (t.content or "") for t in history)


def test_non_owner_turn_is_unaffected(conv_store):
    """Aetheria drafts the same confab; the gate is owner-scoped to Eve, so
    the answer is emitted verbatim — no hold, no extra chat round."""
    fake = _ScriptedChat([
        ChatResponse(content=CONFAB, finish_reason="stop", tool_calls=None, usage={}, raw={}),
    ])
    gate = VerificationGate()  # default owner set = {eve}
    sid = conv_store.new_session("aetheria")
    loop = AgentLoop(
        "aetheria", conv_store, chat_fn=fake, tool_registry=_probe_registry("aetheria"),
        verification_gate=gate, soul_text="",
    )
    response = loop.process_message(sid, "what's in the box?")
    assert response.content == CONFAB
    assert len(fake.calls) == 1  # no forced-verify round


def test_budget_exhaustion_yields_honest_floor(conv_store):
    """If Eve keeps confabulating through the whole budget, the gate downgrades
    to the honest floor rather than emitting the guess."""
    # budget=2 → two holds, then floor. Provide 3 confab responses.
    fake = _ScriptedChat([
        ChatResponse(content=CONFAB, finish_reason="stop", tool_calls=None, usage={}, raw={}),
        ChatResponse(content=CONFAB, finish_reason="stop", tool_calls=None, usage={}, raw={}),
        ChatResponse(content=CONFAB, finish_reason="stop", tool_calls=None, usage={}, raw={}),
    ])
    gate = VerificationGate(forced_verify_budget=2)
    sid = conv_store.new_session("eve")
    loop = AgentLoop(
        "eve", conv_store, chat_fn=fake, tool_registry=_probe_registry(),
        verification_gate=gate, soul_text="",
    )
    response = loop.process_message(sid, "specs?")
    assert response.content == HONEST_FLOOR_ANSWER
    # Two holds → three chat calls total (bounded, no infinite loop).
    assert len(fake.calls) == 3


def test_gate_fails_open_on_detector_exception(conv_store):
    """A detector that raises must NEVER crash the turn — the answer emits as-is
    (degrade to pre-gate behavior)."""
    class Exploding:
        def assess(self, *, answer_text, question_text):
            raise RuntimeError("boom")

    fake = _ScriptedChat([
        ChatResponse(content=CONFAB, finish_reason="stop", tool_calls=None, usage={}, raw={}),
    ])
    gate = VerificationGate(detector=Exploding())
    sid = conv_store.new_session("eve")
    loop = AgentLoop(
        "eve", conv_store, chat_fn=fake, tool_registry=_probe_registry(),
        verification_gate=gate, soul_text="",
    )
    response = loop.process_message(sid, "specs?")
    # Fail-open: emitted normally despite the detector blowing up.
    assert response.content == CONFAB
    assert len(fake.calls) == 1


def test_intent_without_tool_forces_required_tool_choice(conv_store):
    """'Let me pull the current info' with no tool_calls → hold + tool_choice=required."""
    theater = "Let me pull the current info on that and I'll get back to you."
    fake = _ScriptedChat([
        ChatResponse(content=theater, finish_reason="stop", tool_calls=None, usage={}, raw={}),
        ChatResponse(
            content="", finish_reason="tool_calls",
            tool_calls=(_tool_call("c1", "web_search", {"query": "current info"}),),
            usage={}, raw={},
        ),
        ChatResponse(content=GROUNDED, finish_reason="stop", tool_calls=None, usage={}, raw={}),
    ])
    # web_search must be registered so VERIFY_TOOLS can count it
    registry = ToolRegistry(active_agents=("eve",), audit_hook=None)
    registry.register(ToolSpec(
        name="web_search",
        owner="eve",
        schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        handler=lambda args: {"results": []},
        description="search",
    ))
    gate = VerificationGate()
    sid = conv_store.new_session("eve")
    loop = AgentLoop(
        "eve", conv_store, chat_fn=fake, tool_registry=registry,
        verification_gate=gate, soul_text="",
    )
    response = loop.process_message(sid, "what's the latest on that?")
    assert response.content == GROUNDED
    assert fake.calls[1].tool_choice == "required"
    assert theater not in (response.content or "")


def test_verified_turn_is_not_held(conv_store):
    """If a verify tool already ran this turn, the risky answer is emitted —
    the gate only fires when ZERO verify tools ran."""
    fake = _ScriptedChat([
        ChatResponse(
            content="", finish_reason="tool_calls",
            tool_calls=(_tool_call("c1", "system_probe", {"category": "gpu"}),),
            usage={}, raw={},
        ),
        ChatResponse(content=CONFAB, finish_reason="stop", tool_calls=None, usage={}, raw={}),
    ])
    gate = VerificationGate()
    sid = conv_store.new_session("eve")
    loop = AgentLoop(
        "eve", conv_store, chat_fn=fake, tool_registry=_probe_registry(),
        verification_gate=gate, soul_text="",
    )
    response = loop.process_message(sid, "specs?")
    assert response.content == CONFAB
    assert len(fake.calls) == 2  # probe round + answer; no extra hold


# ── Streaming path ───────────────────────────────────────────────────────────

class _ScriptedStream:
    """Yields StreamChunks per scripted round. Each round is a list of chunks."""

    def __init__(self, rounds):
        self._rounds = list(rounds)
        self.calls = []

    def __call__(self, request, server, timeout=60.0):
        self.calls.append(request)
        if not self._rounds:
            raise AssertionError("ScriptedStream ran out of rounds")
        for chunk in self._rounds.pop(0):
            yield chunk


def _content_round(text):
    return [StreamChunk(
        delta=text, finish_reason="stop", tool_calls_delta=None, usage=None, raw={},
    )]


def _toolcall_round(call_id, name, args_obj):
    return [StreamChunk(
        delta="",
        finish_reason="tool_calls",
        tool_calls_delta=[{
            "index": 0, "id": call_id, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args_obj)},
        }],
        usage=None,
        raw={},
    )]


def test_streaming_confab_is_buffered_and_never_emitted_on_hold(conv_store):
    """On the streaming path the drafted confab is buffered (not streamed); a
    hold discards it, so no TokenEvent ever carries the confab to the user."""
    stream = _ScriptedStream([
        _content_round(CONFAB),                                   # held
        _toolcall_round("c1", "system_probe", {"category": "gpu"}),
        _content_round(GROUNDED),                                 # emitted
    ])
    gate = VerificationGate()
    sid = conv_store.new_session("eve")
    loop = AgentLoop(
        "eve", conv_store, stream_fn=stream, tool_registry=_probe_registry(),
        verification_gate=gate, soul_text="",
    )
    events = list(loop.process_message_stream(sid, "will it work on my rig?"))
    token_text = "".join(e.delta for e in events if isinstance(e, TokenEvent))
    done = next(e for e in events if isinstance(e, DoneEvent))
    assert CONFAB not in token_text, "confab must never be streamed"
    assert GROUNDED in token_text
    assert done.content == GROUNDED


def test_streaming_non_owner_streams_live(conv_store):
    """Non-Eve streaming is unchanged: tokens stream live, confab included."""
    stream = _ScriptedStream([_content_round(CONFAB)])
    gate = VerificationGate()
    sid = conv_store.new_session("aetheria")
    loop = AgentLoop(
        "aetheria", conv_store, stream_fn=stream,
        tool_registry=_probe_registry("aetheria"),
        verification_gate=gate, soul_text="",
    )
    events = list(loop.process_message_stream(sid, "what's in the box?"))
    token_text = "".join(e.delta for e in events if isinstance(e, TokenEvent))
    assert token_text == CONFAB
    assert len(stream.calls) == 1
