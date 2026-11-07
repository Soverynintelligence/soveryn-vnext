"""Tests for AgentLoop._coerce_text_tool_calls.

Some models emit tool-call blocks as plain text content when a turn runs
without native tools — seen from Aetheria's Gemma surface on 2026-11-07
(Grok-style function=use_tools blocks) and common in Qwen-style textual tool
syntax. Nothing parsed them, so the block leaked into chat and the agent
looped on "Let me do that" forever.
"""

from __future__ import annotations

import json

from soveryn.agents.loop import AgentLoop
from soveryn.inference.llama_server_client import ChatResponse

TAG_OPEN = "<tool" "_call>"
TAG_CLOSE = "</tool" "_call>"


def _resp(content: str, tool_calls=None) -> ChatResponse:
    return ChatResponse(
        content=content,
        finish_reason="stop",
        tool_calls=tool_calls,
        usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        raw={},
    )


def _grok_block(name: str, args: dict) -> str:
    return (
        f"{TAG_OPEN}\n<function=use_tools>\n"
        + json.dumps({"toolName": name, "arguments": json.dumps(args)})
        + f"\n</function>\n{TAG_CLOSE}"
    )


def _plain_block(name: str, args: dict) -> str:
    return TAG_OPEN + "\n" + json.dumps({"name": name, "arguments": args}) + "\n" + TAG_CLOSE


class TestCoerceTextToolCalls:
    def test_grok_style_block_becomes_native_tool_call(self):
        content = (
            "I don't have the task details in front of me right now. "
            "Let me do that.\n\n" + _grok_block("read_collab", {"taskId": "18eebfdc"})
        )
        out = AgentLoop._coerce_text_tool_calls(_resp(content))
        assert out.tool_calls is not None and len(out.tool_calls) == 1
        tc = out.tool_calls[0]
        assert tc["function"]["name"] == "read_collab"
        assert json.loads(tc["function"]["arguments"]) == {"taskId": "18eebfdc"}
        assert TAG_OPEN not in out.content
        assert "Let me do that." in out.content

    def test_plain_block_becomes_native_tool_call(self):
        content = "Reading it now.\n" + _plain_block("read_file", {"path": "/tmp/x"})
        out = AgentLoop._coerce_text_tool_calls(_resp(content))
        assert out.tool_calls is not None
        assert out.tool_calls[0]["function"]["name"] == "read_file"
        assert json.loads(out.tool_calls[0]["function"]["arguments"]) == {
            "path": "/tmp/x"
        }
        assert TAG_OPEN not in out.content

    def test_multiple_blocks_yield_multiple_calls(self):
        content = _grok_block("a", {"x": 1}) + "\n" + _plain_block("b", {"y": 2})
        out = AgentLoop._coerce_text_tool_calls(_resp(content))
        assert out.tool_calls is not None and len(out.tool_calls) == 2
        assert [tc["function"]["name"] for tc in out.tool_calls] == ["a", "b"]

    def test_unclosed_block_left_alone(self):
        content = "thinking out loud " + TAG_OPEN + " but never close it"
        out = AgentLoop._coerce_text_tool_calls(_resp(content))
        assert out.tool_calls is None
        assert TAG_OPEN in out.content

    def test_native_tool_calls_take_precedence(self):
        native = (
            {
                "id": "x",
                "type": "function",
                "function": {"name": "t", "arguments": "{}"},
            },
        )
        content = "junk " + _grok_block("ignored", {})
        out = AgentLoop._coerce_text_tool_calls(_resp(content, tool_calls=native))
        assert out.tool_calls == native
        assert TAG_OPEN in out.content  # untouched — native path handles it

    def test_empty_content_untouched(self):
        out = AgentLoop._coerce_text_tool_calls(_resp(""))
        assert out.tool_calls is None

    def test_malformed_json_left_alone(self):
        content = TAG_OPEN + "<function=use_tools>{not json}</function>" + TAG_CLOSE
        out = AgentLoop._coerce_text_tool_calls(_resp(content))
        assert out.tool_calls is None

    def test_unknown_tool_name_still_coerced(self):
        # Dispatch/validation is the registry's job; coercion only converts.
        content = _grok_block("no_such_tool", {"a": 1})
        out = AgentLoop._coerce_text_tool_calls(_resp(content))
        assert out.tool_calls is not None
        assert out.tool_calls[0]["function"]["name"] == "no_such_tool"

    def test_name_falls_back_to_json_field(self):
        content = TAG_OPEN + "\n" + json.dumps({"toolName": "solo", "taskId": "9"}) + "\n" + TAG_CLOSE
        out = AgentLoop._coerce_text_tool_calls(_resp(content))
        assert out.tool_calls is not None
        assert out.tool_calls[0]["function"]["name"] == "solo"
        assert json.loads(out.tool_calls[0]["function"]["arguments"]) == {"taskId": "9"}
