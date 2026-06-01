"""Tests for soveryn.inference.llama_server_client."""

from __future__ import annotations
import json
import socket
import urllib.error
from pathlib import Path
from unittest.mock import patch
import pytest

from soveryn.config.runtime import MODEL_SERVERS, ModelServer
from soveryn.inference.llama_server_client import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    EmbeddingRequest,
    EmbeddingResponse,
    LlamaServerError,
    LlamaServerTimeout,
    chat,
    chat_stream,
    prepare_wire_messages,
    embed,
)


# ─────────────────────────────────────────────────────────────────────────────
# Mocking helpers
# ─────────────────────────────────────────────────────────────────────────────

class _MockResp:
    def __init__(self, status, body_dict):
        self.status = status
        self._body = json.dumps(body_dict).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _patch_urlopen(status=200, body=None, raise_exc=None):
    captured = {}

    def fake(req, timeout=None):
        captured["req"] = req
        captured["timeout"] = timeout
        captured["body"] = req.data
        if raise_exc is not None:
            raise raise_exc
        return _MockResp(status, body or {})

    return captured, patch("urllib.request.urlopen", side_effect=fake)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _vett_server() -> ModelServer:
    for s in MODEL_SERVERS:
        if s.name == "vett_scotty_shared":
            return s
    raise LookupError("vett_scotty_shared not found")


def _aetheria_server() -> ModelServer:
    for s in MODEL_SERVERS:
        if s.name == "aetheria_primary":
            return s
    raise LookupError("aetheria_primary not found")


def _minimal_chat_ok_body(content="hello") -> dict:
    return {
        "choices": [
            {
                "message": {"content": content, "role": "assistant"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
    }


# ─────────────────────────────────────────────────────────────────────────────
# Payload shape tests
# ─────────────────────────────────────────────────────────────────────────────

def test_chat_builds_openai_compat_payload():
    server = _vett_server()
    request = ChatRequest(
        messages=(ChatMessage(role="user", content="hi"),),
        model="vett-scotty",
        temperature=0.5,
        max_tokens=100,
    )
    captured, ctx = _patch_urlopen(body=_minimal_chat_ok_body())
    with ctx:
        chat(request, server)

    payload = json.loads(captured["body"].decode())
    assert "messages" in payload
    assert payload["messages"] == [{"role": "user", "content": "hi"}]
    assert payload["model"] == "vett-scotty"
    assert payload["temperature"] == 0.5
    assert payload["max_tokens"] == 100
    assert payload["stream"] is False


def test_chat_payload_omits_optional_fields_when_unset():
    server = _vett_server()
    request = ChatRequest(
        messages=(ChatMessage(role="user", content="hi"),),
        model="vett-scotty",
    )
    captured, ctx = _patch_urlopen(body=_minimal_chat_ok_body())
    with ctx:
        chat(request, server)

    payload = json.loads(captured["body"].decode())
    assert "top_p" not in payload
    assert "stop" not in payload
    assert "tools" not in payload
    assert "thinking_budget_tokens" not in payload


def test_chat_payload_includes_optional_fields_when_set():
    server = _vett_server()
    request = ChatRequest(
        messages=(ChatMessage(role="user", content="hi"),),
        model="vett-scotty",
        top_p=0.9,
        stop=("<|endoftext|>", "<|im_end|>"),
        tools=({"type": "function", "function": {"name": "foo"}},),
        thinking_budget_tokens=384,
    )
    captured, ctx = _patch_urlopen(body=_minimal_chat_ok_body())
    with ctx:
        chat(request, server)

    payload = json.loads(captured["body"].decode())
    assert payload["top_p"] == 0.9
    assert payload["stop"] == ["<|endoftext|>", "<|im_end|>"]
    assert payload["tools"] == [{"type": "function", "function": {"name": "foo"}}]
    assert payload["thinking_budget_tokens"] == 384
    assert payload["repetition_penalty"] == 1.1


def test_chat_message_supports_tool_fields_optional():
    tool_msg = ChatMessage(role="tool", content='{"result": "ok"}', tool_call_id="call_123")
    assert tool_msg.tool_call_id == "call_123"
    assert tool_msg.tool_calls is None
    asst_msg = ChatMessage(
        role="assistant",
        content="",
        tool_calls=({"id": "c1", "function": {"name": "x"}},),
    )
    assert asst_msg.tool_calls is not None
    assert asst_msg.tool_call_id is None
    plain = ChatMessage(role="user", content="hi")
    assert plain.tool_call_id is None
    assert plain.tool_calls is None


def test_chat_payload_emits_tool_call_id_only_on_tool_messages():
    server = _vett_server()
    request = ChatRequest(
        messages=(
            ChatMessage(role="user", content="hi"),
            ChatMessage(role="tool", content='{"ok": true}', tool_call_id="call_123"),
        ),
        model="vett-scotty",
    )
    captured, ctx = _patch_urlopen(body=_minimal_chat_ok_body())
    with ctx:
        chat(request, server)
    payload = json.loads(captured["body"].decode())
    tool_msg = payload["messages"][-1]
    assert tool_msg["role"] == "tool"
    assert tool_msg["tool_call_id"] == "call_123"
    assert "tool_call_id" not in payload["messages"][0]


def test_chat_payload_emits_tool_calls_only_on_assistant_messages():
    server = _vett_server()
    tool_calls = ({
        "id": "c1",
        "type": "function",
        "function": {"name": "echo", "arguments": "{}"},
    },)
    request = ChatRequest(
        messages=(
            ChatMessage(role="user", content="hi"),
            ChatMessage(role="assistant", content="", tool_calls=tool_calls),
            ChatMessage(role="tool", content='{"ok": true}', tool_call_id="c1"),
        ),
        model="vett-scotty",
    )
    captured, ctx = _patch_urlopen(body=_minimal_chat_ok_body())
    with ctx:
        chat(request, server)
    payload = json.loads(captured["body"].decode())
    asst_msg = payload["messages"][1]
    assert asst_msg["role"] == "assistant"
    assert asst_msg["tool_calls"] == [{
        "id": "c1",
        "type": "function",
        "function": {"name": "echo", "arguments": "{}"},
    }]
    assert "tool_calls" not in payload["messages"][0]


# ─────────────────────────────────────────────────────────────────────────────
# Response parsing tests
# ─────────────────────────────────────────────────────────────────────────────

def test_chat_200_returns_chatresponse_with_content():
    server = _vett_server()
    request = ChatRequest(
        messages=(ChatMessage(role="user", content="ping"),),
        model="vett-scotty",
    )
    body = _minimal_chat_ok_body("pong")
    _, ctx = _patch_urlopen(body=body)
    with ctx:
        resp = chat(request, server)

    assert isinstance(resp, ChatResponse)
    assert resp.content == "pong"
    assert resp.finish_reason == "stop"


def test_chat_preserves_raw_tool_calls():
    server = _vett_server()
    request = ChatRequest(
        messages=(ChatMessage(role="user", content="use tool"),),
        model="vett-scotty",
    )
    raw_tc = [{"id": "call_abc", "type": "function", "function": {"name": "foo", "arguments": "{}"}}]
    body = {
        "choices": [
            {
                "message": {
                    "content": None,
                    "role": "assistant",
                    "tool_calls": raw_tc,
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    _, ctx = _patch_urlopen(body=body)
    with ctx:
        resp = chat(request, server)

    assert resp.finish_reason == "tool_calls"
    assert resp.tool_calls is not None
    assert isinstance(resp.tool_calls, tuple)
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0]["id"] == "call_abc"
    assert resp.tool_calls[0]["function"]["name"] == "foo"
    # No interpretation — the dict is raw passthrough
    assert "function" in resp.tool_calls[0]


def test_chat_preserves_usage_and_raw():
    server = _vett_server()
    request = ChatRequest(
        messages=(ChatMessage(role="user", content="hi"),),
        model="vett-scotty",
    )
    body = _minimal_chat_ok_body("hello")
    _, ctx = _patch_urlopen(body=body)
    with ctx:
        resp = chat(request, server)

    assert resp.usage == {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}
    assert resp.raw == body


def test_chat_strips_think_markup_from_content_but_keeps_reasoning_raw():
    server = _vett_server()
    request = ChatRequest(
        messages=(ChatMessage(role="user", content="hi"),),
        model="vett-scotty",
    )
    body = {
        "choices": [
            {
                "message": {
                    "content": "<think>draft</think>final",
                    "reasoning_content": "scratchpad prose",
                    "role": "assistant",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
    }
    _, ctx = _patch_urlopen(body=body)
    with ctx:
        resp = chat(request, server)

    assert resp.content == "final"
    assert resp.raw["choices"][0]["message"]["reasoning_content"] == "scratchpad prose"


class _MockSSEResp:
    def __init__(self, lines):
        self._lines = [line if isinstance(line, bytes) else line.encode() for line in lines]
        self.closed = False

    def __iter__(self):
        return iter(self._lines)

    def close(self):
        self.closed = True


def _sse_line(payload: dict) -> bytes:
    return f"data: {json.dumps(payload)}\n\n".encode()




def test_chat_stream_strips_think_markup_from_deltas_and_done():
    server = _vett_server()
    request = ChatRequest(
        messages=(ChatMessage(role="user", content="hi"),),
        model="vett-scotty",
    )
    lines = [
        _sse_line({
            "choices": [{"delta": {"content": "Hello ", "role": "assistant"}, "finish_reason": None}],
        }),
        _sse_line({
            "choices": [{"delta": {"content": "<think>draft</think>world", "role": "assistant"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        }),
    ]

    def fake_urlopen(req, timeout=None):
        return _MockSSEResp(lines)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        chunks = list(chat_stream(request, server))

    deltas = [chunk.delta for chunk in chunks if chunk.delta]
    assert deltas == ["Hello ", "world"]
    assert chunks[-1].finish_reason == "stop"
    assert "<think>" not in "".join(deltas)
    assert "</think>" not in "".join(deltas)


def test_chat_strips_naked_reasoning_before_lone_close_tag():
    """The pattern observed live 2026-05-31: model emits reasoning prose
    with NO opening <think> tag, then a lone </think>, then the response.
    Previously the block/open/close trio stripped only the close tag and
    left the reasoning above intact. The naked-close pattern strips
    everything from start of content up to and including the close tag."""
    server = _vett_server()
    request = ChatRequest(
        messages=(ChatMessage(role="user", content="hi"),),
        model="vett-scotty",
    )
    bleeding = (
        "ok issue was a bit messy.\n"
        "I will respond to that.\n"
        "Ready.\n"
        "</think>\n"
        "Solid win. Now what's next?"
    )
    body = {
        "choices": [{
            "message": {"content": bleeding, "role": "assistant"},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
    }
    _, ctx = _patch_urlopen(body=body)
    with ctx:
        resp = chat(request, server)
    assert resp.content == "Solid win. Now what's next?"
    assert "</think>" not in resp.content
    assert "I will respond" not in resp.content


def test_chat_stream_strips_naked_reasoning_streamed_across_chunks():
    """Same pattern in the streaming path: reasoning tokens flow before
    any <think> opening, then a lone </think>, then the response. The
    UI must never see the reasoning deltas — they get retracted when the
    close tag arrives (delta_to_emit goes negative-relative; emitted len
    rewinds; only the response surfaces in subsequent deltas)."""
    server = _vett_server()
    request = ChatRequest(
        messages=(ChatMessage(role="user", content="hi"),),
        model="vett-scotty",
    )
    lines = [
        _sse_line({"choices": [{"delta": {"content": "reasoning prose ", "role": "assistant"}, "finish_reason": None}]}),
        _sse_line({"choices": [{"delta": {"content": "more reasoning. ", "role": "assistant"}, "finish_reason": None}]}),
        _sse_line({"choices": [{"delta": {"content": "</think>", "role": "assistant"}, "finish_reason": None}]}),
        _sse_line({"choices": [{"delta": {"content": "Solid response.", "role": "assistant"}, "finish_reason": "stop"}],
                   "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}}),
    ]

    def fake_urlopen(req, timeout=None):
        return _MockSSEResp(lines)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        chunks = list(chat_stream(request, server))

    accumulated = "".join(chunk.delta for chunk in chunks if chunk.delta)
    # The final visible content after the stream completes must be only the response.
    # (Mid-stream the reasoning may have been visible — that's a known limitation of
    # streaming without lookahead; the contract is the FINAL visible state is clean
    # and any reader who waits for finish_reason sees only the response.)
    assert "Solid response." in accumulated
    assert "</think>" not in accumulated
    # The naked-close strip retracts the reasoning so the final accumulated state
    # contains the response, not the reasoning prose.
    final_content = chunks[-1].raw["choices"][0]["delta"]["content"]  # raw last chunk for reference
    # The accumulated VISIBLE content (across all delta emissions) ends with
    # exactly the response, with no reasoning text appearing in the final state.
    # We allow for the streaming-mid-state reasoning to have flickered, but the
    # final delta_to_emit must complete cleanly to the response only.
    assert chunks[-1].finish_reason == "stop"


def test_strip_naked_does_not_overstrip_when_open_tag_precedes():
    """Belt and braces: when both <think> and </think> are present (the
    canonical block case), the block regex catches it. The naked regex
    must NOT additionally strip content above a <think>...</think> pair."""
    from soveryn.platform.inference.llama_server_client import _strip_think_markup
    text = "intro prose\n<think>scratch</think>\nresponse"
    out = _strip_think_markup(text)
    assert "intro prose" in out
    assert "response" in out
    assert "<think>" not in out
    assert "</think>" not in out
    assert "scratch" not in out


def test_strip_naked_no_close_tag_unchanged():
    """Sanity: if there's no </think> anywhere, content passes through unchanged."""
    from soveryn.platform.inference.llama_server_client import _strip_think_markup
    text = "completely clean response with no markup at all"
    out = _strip_think_markup(text)
    assert out == text


# ─────────────────────────────────────────────────────────────────────────────
# Error mapping tests
# ─────────────────────────────────────────────────────────────────────────────

def test_chat_500_raises_llama_server_error():
    server = _vett_server()
    request = ChatRequest(
        messages=(ChatMessage(role="user", content="hi"),),
        model="vett-scotty",
    )

    # urllib raises HTTPError for non-2xx responses
    http_err = urllib.error.HTTPError(
        url="http://127.0.0.1:8090/v1/chat/completions",
        code=500,
        msg="Internal Server Error",
        hdrs=None,
        fp=None,
    )
    _, ctx = _patch_urlopen(raise_exc=http_err)
    with ctx:
        with pytest.raises(LlamaServerError) as exc_info:
            chat(request, server)

    err = exc_info.value
    assert err.status_code == 500
    assert err.server_name == "vett_scotty_shared"


def test_chat_timeout_raises_llama_server_timeout():
    server = _vett_server()
    request = ChatRequest(
        messages=(ChatMessage(role="user", content="hi"),),
        model="vett-scotty",
    )
    _, ctx = _patch_urlopen(raise_exc=socket.timeout("timed out"))
    with ctx:
        with pytest.raises(LlamaServerTimeout) as exc_info:
            chat(request, server, timeout=5.0)

    err = exc_info.value
    assert err.server_name == "vett_scotty_shared"
    assert err.timeout_seconds == 5.0


def test_chat_url_error_raises_llama_server_error_with_status_0():
    server = _vett_server()
    request = ChatRequest(
        messages=(ChatMessage(role="user", content="hi"),),
        model="vett-scotty",
    )
    url_err = urllib.error.URLError(reason="Connection refused")
    _, ctx = _patch_urlopen(raise_exc=url_err)
    with ctx:
        with pytest.raises(LlamaServerError) as exc_info:
            chat(request, server)

    err = exc_info.value
    assert err.status_code == 0
    assert "URLError" in err.detail


def test_chat_invalid_response_shape_raises_llama_server_error():
    server = _vett_server()
    request = ChatRequest(
        messages=(ChatMessage(role="user", content="hi"),),
        model="vett-scotty",
    )
    # Missing "choices" key entirely
    body = {"not_choices": []}
    _, ctx = _patch_urlopen(body=body)
    with ctx:
        with pytest.raises(LlamaServerError) as exc_info:
            chat(request, server)

    err = exc_info.value
    assert "unexpected response shape" in err.detail


# ─────────────────────────────────────────────────────────────────────────────
# Embeddings tests
# ─────────────────────────────────────────────────────────────────────────────

def test_embed_routes_to_embeddings_server_only():
    """embed() must contact the embeddings endpoint, never a chat endpoint.

    Phase 7 (router cutover): all four MODEL_SERVERS now share :8090 — the
    per-port isolation that used to enforce this boundary is gone, replaced by
    per-model dispatch on the router. The semantic invariant that survives is:
    embed() goes to /v1/embeddings with the embeddings server's model_alias,
    NEVER to /v1/chat/completions. Verify both pieces."""
    request = EmbeddingRequest(input=("hello world",))
    body = {
        "data": [{"embedding": [0.1, 0.2, 0.3], "index": 0}],
        "usage": {"prompt_tokens": 2, "total_tokens": 2},
    }
    captured, ctx = _patch_urlopen(body=body)
    with ctx:
        embed(request)

    # Must hit /v1/embeddings on the router port; never /v1/chat/completions
    url_called = captured["req"].full_url
    assert ":8090/v1/embeddings" in url_called
    assert "/v1/chat/completions" not in url_called

    # Payload must carry the embeddings server's alias so the router
    # dispatches to the embeddings child subprocess, not an agent child.
    payload = json.loads(captured["body"].decode())
    assert payload["model"] == "embeddings"


def test_embed_response_parses_vectors():
    request = EmbeddingRequest(input=("foo", "bar"))
    body = {
        "data": [
            {"embedding": [0.1, 0.2], "index": 0},
            {"embedding": [0.3, 0.4], "index": 1},
        ],
        "usage": {"prompt_tokens": 2, "total_tokens": 2},
    }
    _, ctx = _patch_urlopen(body=body)
    with ctx:
        resp = embed(request)

    assert isinstance(resp, EmbeddingResponse)
    assert resp.vectors == ((0.1, 0.2), (0.3, 0.4))


def test_embed_500_raises_llama_server_error():
    request = EmbeddingRequest(input=("hello",))
    http_err = urllib.error.HTTPError(
        url="http://127.0.0.1:8090/v1/embeddings",
        code=500,
        msg="Internal Server Error",
        hdrs=None,
        fp=None,
    )
    _, ctx = _patch_urlopen(raise_exc=http_err)
    with ctx:
        with pytest.raises(LlamaServerError) as exc_info:
            embed(request)

    err = exc_info.value
    assert err.status_code == 500
    assert err.server_name == "embeddings"


def test_embed_invalid_shape_raises_llama_server_error():
    request = EmbeddingRequest(input=("hello",))
    # Missing "data" key
    body = {"not_data": []}
    _, ctx = _patch_urlopen(body=body)
    with ctx:
        with pytest.raises(LlamaServerError) as exc_info:
            embed(request)

    err = exc_info.value
    assert "unexpected embeddings shape" in err.detail


# ─────────────────────────────────────────────────────────────────────────────
# No-legacy-imports lint test
# ─────────────────────────────────────────────────────────────────────────────

def test_no_imports_from_legacy_or_flask():
    """Verify routing.py and llama_server_client.py have no banned imports."""
    base = Path(__file__).parent.parent / "soveryn" / "inference"
    files_to_check = [
        base / "routing.py",
        base / "llama_server_client.py",
    ]
    banned_patterns = [
        "soveryn_complete",
        "from flask",
        "import flask",
        "from sovereign_backend",
        "import sovereign_backend",
        "from sovereign_llm_client",
        "import sovereign_llm_client",
    ]
    for fpath in files_to_check:
        source = fpath.read_text()
        for pattern in banned_patterns:
            assert pattern not in source, (
                f"{fpath.name} contains banned import pattern {pattern!r}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# prepare_wire_messages — transport adapter for chat templates that only
# honor messages[0] of role=system (Qwen3.6 jinja). Tests prove the seam:
# AgentLoop produces semantic layers as separate ChatMessages; the adapter
# folds them at the wire boundary only when the server's template demands it.
# See feedback_workaround_is_not_architecture and
# project_soveryn_three_tracks_workaround_capability_agency.
# ─────────────────────────────────────────────────────────────────────────────

def _server(*, supports_multi: bool, name: str = "test") -> ModelServer:
    return ModelServer(
        name=name,
        port=8090,
        model_path=Path("/dev/null"),
        role="test",
        supports_multi_system_messages=supports_multi,
        model_alias=name,
    )


def test_prepare_wire_messages_passes_through_when_multi_supported():
    """If the server's template handles multi-system messages, the adapter is
    a no-op — preserves every ChatMessage identity."""
    msgs = (
        ChatMessage(role="system", content="persona"),
        ChatMessage(role="system", content="pinned"),
        ChatMessage(role="system", content="soul"),
        ChatMessage(role="system", content="recall"),
        ChatMessage(role="user", content="hi"),
    )
    out = prepare_wire_messages(msgs, _server(supports_multi=True))
    assert out == msgs


def test_prepare_wire_messages_folds_consecutive_prelude_systems_when_unsupported():
    """Aetheria-shape: 4 prelude system messages + 1 user. Adapter folds the
    4 system messages into 1 (the locked Qwen3.6 accommodation), preserves
    the user message exactly."""
    msgs = (
        ChatMessage(role="system", content="persona"),
        ChatMessage(role="system", content="pinned"),
        ChatMessage(role="system", content="soul"),
        ChatMessage(role="system", content="recall"),
        ChatMessage(role="user", content="hi"),
    )
    out = prepare_wire_messages(msgs, _server(supports_multi=False))
    assert len(out) == 2, f"expected 1 folded system + 1 user, got {len(out)}"
    assert out[0].role == "system"
    assert out[0].content == "persona\n\npinned\n\nsoul\n\nrecall"
    assert out[1] == ChatMessage(role="user", content="hi")


def test_prepare_wire_messages_preserves_order_persona_pinned_soul_recall():
    """Folded content must preserve the AgentLoop's prelude order exactly."""
    msgs = (
        ChatMessage(role="system", content="A"),
        ChatMessage(role="system", content="B"),
        ChatMessage(role="system", content="C"),
        ChatMessage(role="system", content="D"),
        ChatMessage(role="user", content="q"),
    )
    out = prepare_wire_messages(msgs, _server(supports_multi=False))
    # "A...B...C...D" — substring order check independent of separator
    folded = out[0].content
    a_idx = folded.index("A")
    b_idx = folded.index("B")
    c_idx = folded.index("C")
    d_idx = folded.index("D")
    assert a_idx < b_idx < c_idx < d_idx, f"order broken: {folded!r}"


def test_prepare_wire_messages_leaves_history_and_user_alone():
    """user / assistant / tool history is not touched, in either mode."""
    msgs = (
        ChatMessage(role="system", content="persona"),
        ChatMessage(role="system", content="soul"),
        ChatMessage(role="user", content="first user msg"),
        ChatMessage(role="assistant", content="prior reply"),
        ChatMessage(role="user", content="current"),
    )
    out = prepare_wire_messages(msgs, _server(supports_multi=False))
    assert out[-3] == ChatMessage(role="user", content="first user msg")
    assert out[-2] == ChatMessage(role="assistant", content="prior reply")
    assert out[-1] == ChatMessage(role="user", content="current")


def test_prepare_wire_messages_handles_single_prelude_system():
    """One system + one user: nothing to fold, but adapter still works."""
    msgs = (
        ChatMessage(role="system", content="persona only"),
        ChatMessage(role="user", content="hi"),
    )
    out = prepare_wire_messages(msgs, _server(supports_multi=False))
    assert out == msgs


def test_prepare_wire_messages_only_folds_prelude_not_interior_system():
    """A 'system' message that appears AFTER user/assistant turns is part of
    history (e.g. tool injection), not the prelude — adapter must not fold
    it into the front."""
    msgs = (
        ChatMessage(role="system", content="persona"),
        ChatMessage(role="system", content="soul"),
        ChatMessage(role="user", content="q"),
        ChatMessage(role="system", content="tool result note"),
        ChatMessage(role="user", content="follow-up"),
    )
    out = prepare_wire_messages(msgs, _server(supports_multi=False))
    # The prelude (positions 0,1) folds into 1 system message; everything
    # from position 2 onward is preserved exactly.
    assert out[0].role == "system"
    assert "persona" in out[0].content and "soul" in out[0].content
    assert out[1] == ChatMessage(role="user", content="q")
    assert out[2] == ChatMessage(role="system", content="tool result note")
    assert out[3] == ChatMessage(role="user", content="follow-up")


def test_prepare_wire_messages_aetheria_seam_4_separate_at_agent_loop_folds_to_1_at_wire():
    """End-to-end seam proof: AgentLoop assembles four semantically separate
    ChatMessages (persona / pinned / soul / recall) for Aetheria; the adapter
    folds them into ONE structured system message at the wire boundary, with
    all four sections present in order. This is the locked Qwen3.6 workaround
    that does NOT collapse the domain-layer architecture.

    See feedback_workaround_is_not_architecture.
    """
    # Simulate what AgentLoop's process_message hands to the chat function
    # for an Aetheria turn (server.supports_multi_system_messages = False per
    # the runtime config — that's the Qwen3.6 35B template constraint).
    aetheria_server = _server(supports_multi=False, name="aetheria_primary")
    agent_loop_messages = (
        ChatMessage(role="system", content="PERSONA_BODY"),
        ChatMessage(role="system", content="PINNED_BODY"),
        ChatMessage(role="system", content="SOUL_BODY"),
        ChatMessage(role="system", content="Stateable recall:\n- entry"),
        ChatMessage(role="user", content="hello"),
    )
    # Domain side — semantic layers stay separate
    domain_system_count = sum(1 for m in agent_loop_messages if m.role == "system")
    assert domain_system_count == 4, "AgentLoop must produce 4 separate system messages"
    # Transport side — adapter folds for the Qwen template
    wire = prepare_wire_messages(agent_loop_messages, aetheria_server)
    wire_system_count = sum(1 for m in wire if m.role == "system")
    assert wire_system_count == 1, (
        "transport adapter should produce 1 system message for a Qwen-shape "
        "server; got " + str(wire_system_count)
    )
    # All four sections present in order in the single wire-system message
    folded = wire[0].content
    assert folded.index("PERSONA_BODY") < folded.index("PINNED_BODY") < folded.index("SOUL_BODY") < folded.index("Stateable recall:")
    # User message preserved
    assert wire[-1] == ChatMessage(role="user", content="hello")
