"""Tests for AgentLoop's tool-call iteration loop (Track 2, non-stream path)."""

import json

import pytest

from soveryn.agents.loop import AgentLoop
from soveryn.memory.conversation_store import ConversationStore
from soveryn.platform.inference.llama_server_client import ChatResponse
from soveryn.platform.tools.registry import ToolRegistry, ToolSpec


@pytest.fixture
def conv_store(tmp_path):
    return ConversationStore(tmp_path / "conv.db")


def _make_registry(handler, *, tool_name="echo", owner="aetheria"):
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


class _ScriptedChat:
    def __init__(self, responses: list[ChatResponse]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def __call__(self, request, server, timeout=60.0):
        self.calls.append({"request": request, "server": server, "timeout": timeout})
        if not self._responses:
            raise AssertionError("_ScriptedChat ran out of scripted responses")
        return self._responses.pop(0)


def _tool_call(call_id, name, args_obj):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args_obj)},
    }


def test_single_tool_call_dispatched_and_result_threaded_back(conv_store):
    registry = _make_registry(lambda args: {"echoed": args["text"]})
    fake = _ScriptedChat([
        ChatResponse(
            content="",
            finish_reason="tool_calls",
            tool_calls=(_tool_call("call_a", "echo", {"text": "hi"}),),
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            raw={},
        ),
        ChatResponse(
            content="echo result was hi",
            finish_reason="stop",
            tool_calls=None,
            usage={"prompt_tokens": 2, "completion_tokens": 2, "total_tokens": 4},
            raw={},
        ),
    ])
    sid = conv_store.new_session("aetheria")
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake, tool_registry=registry, max_tool_rounds=4)
    response = loop.process_message(sid, "use the echo tool")

    assert len(fake.calls) == 2
    second_msgs = fake.calls[1]["request"].messages
    assistant_msg = next(m for m in second_msgs if m.role == "assistant")
    assert assistant_msg.tool_calls == (_tool_call("call_a", "echo", {"text": "hi"}),)
    tool_msg = next(m for m in second_msgs if m.role == "tool")
    assert tool_msg.tool_call_id == "call_a"
    assert json.loads(tool_msg.content) == {"echoed": "hi"}
    assert response.content == "echo result was hi"


def test_two_tool_calls_in_one_round_both_dispatched(conv_store):
    registry = _make_registry(lambda args: {"echoed": args["text"]})
    fake = _ScriptedChat([
        ChatResponse(
            content="",
            finish_reason="tool_calls",
            tool_calls=(
                _tool_call("c1", "echo", {"text": "a"}),
                _tool_call("c2", "echo", {"text": "b"}),
            ),
            usage={}, raw={},
        ),
        ChatResponse(content="done", finish_reason="stop", tool_calls=None, usage={}, raw={}),
    ])
    sid = conv_store.new_session("aetheria")
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake, tool_registry=registry)
    loop.process_message(sid, "use the echo tool twice")
    tool_msgs = [m for m in fake.calls[1]["request"].messages if m.role == "tool"]
    assert len(tool_msgs) == 2
    assert {m.tool_call_id for m in tool_msgs} == {"c1", "c2"}


def test_max_tool_rounds_bounded(conv_store):
    registry = _make_registry(lambda args: {"echoed": args["text"]})

    def looping_response():
        return ChatResponse(
            content="",
            finish_reason="tool_calls",
            tool_calls=(_tool_call("call_x", "echo", {"text": "loop"}),),
            usage={}, raw={},
        )

    fake = _ScriptedChat([looping_response() for _ in range(10)])
    sid = conv_store.new_session("aetheria")
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake, tool_registry=registry, max_tool_rounds=3)
    response = loop.process_message(sid, "go")
    assert len(fake.calls) == 4
    assert response.finish_reason == "tool_round_limit"


def test_tool_arg_error_surfaces_as_tool_result_not_exception(conv_store):
    registry = _make_registry(lambda args: {"echoed": args["text"]})
    fake = _ScriptedChat([
        ChatResponse(
            content="",
            finish_reason="tool_calls",
            tool_calls=(_tool_call("c1", "echo", {}),),
            usage={}, raw={},
        ),
        ChatResponse(content="recovered", finish_reason="stop", tool_calls=None, usage={}, raw={}),
    ])
    sid = conv_store.new_session("aetheria")
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake, tool_registry=registry)
    response = loop.process_message(sid, "go")
    tool_msg = next(m for m in fake.calls[1]["request"].messages if m.role == "tool")
    body = json.loads(tool_msg.content)
    assert body["error"] == "ToolArgError"
    assert "text" in body["message"]
    assert response.content == "recovered"


def test_handler_runtime_error_surfaces_as_tool_result_not_exception(conv_store):
    """A tool handler raising anything other than ToolArgError (DB lock,
    transient failure, bug, etc.) must surface as a tool-result payload
    so the model can see 'this tool failed' and recover. Without this,
    a single tool handler raise would crash the whole turn."""

    def crashing_handler(args):
        raise RuntimeError("simulated DB lock")

    registry = _make_registry(crashing_handler)
    fake = _ScriptedChat([
        ChatResponse(
            content="",
            finish_reason="tool_calls",
            tool_calls=(_tool_call("c1", "echo", {"text": "x"}),),
            usage={}, raw={},
        ),
        ChatResponse(content="recovered from handler error", finish_reason="stop",
                     tool_calls=None, usage={}, raw={}),
    ])
    sid = conv_store.new_session("aetheria")
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake, tool_registry=registry)
    response = loop.process_message(sid, "go")
    tool_msg = next(m for m in fake.calls[1]["request"].messages if m.role == "tool")
    body = json.loads(tool_msg.content)
    assert body["error"] == "RuntimeError"
    assert "simulated DB lock" in body["message"]
    assert response.content == "recovered from handler error"


def test_handler_value_error_carries_real_exception_type_not_tool_arg_error(conv_store):
    """ValueError from inside a handler must NOT be misreported as
    ToolArgError — the latter is for schema-validation failures only.
    Real exception class name carries through."""

    def value_error_handler(args):
        raise ValueError("genuine internal value error")

    registry = _make_registry(value_error_handler)
    fake = _ScriptedChat([
        ChatResponse(
            content="",
            finish_reason="tool_calls",
            tool_calls=(_tool_call("c1", "echo", {"text": "x"}),),
            usage={}, raw={},
        ),
        ChatResponse(content="ok", finish_reason="stop", tool_calls=None, usage={}, raw={}),
    ])
    sid = conv_store.new_session("aetheria")
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake, tool_registry=registry)
    loop.process_message(sid, "go")
    tool_msg = next(m for m in fake.calls[1]["request"].messages if m.role == "tool")
    body = json.loads(tool_msg.content)
    assert body["error"] == "ValueError"
    assert body["error"] != "ToolArgError"


def test_no_registry_passes_tool_calls_through_unchanged(conv_store):
    fake = _ScriptedChat([
        ChatResponse(
            content="",
            finish_reason="tool_calls",
            tool_calls=(_tool_call("c1", "echo", {"text": "x"}),),
            usage={}, raw={},
        ),
    ])
    sid = conv_store.new_session("aetheria")
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake)
    response = loop.process_message(sid, "go")
    assert len(fake.calls) == 1
    assert response.tool_calls is not None


def test_tools_field_in_chat_request_when_registry_present(conv_store):
    registry = _make_registry(lambda args: {"echoed": args["text"]})
    fake = _ScriptedChat([
        ChatResponse(content="done", finish_reason="stop", tool_calls=None, usage={}, raw={}),
    ])
    sid = conv_store.new_session("aetheria")
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake, tool_registry=registry)
    loop.process_message(sid, "hi")
    request = fake.calls[0]["request"]
    assert request.tools is not None
    assert len(request.tools) == 1
    assert request.tools[0]["function"]["name"] == "echo"
