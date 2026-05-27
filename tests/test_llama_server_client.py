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


def test_chat_payload_includes_optional_fields_when_set():
    server = _vett_server()
    request = ChatRequest(
        messages=(ChatMessage(role="user", content="hi"),),
        model="vett-scotty",
        top_p=0.9,
        stop=("<|endoftext|>", "<|im_end|>"),
        tools=({"type": "function", "function": {"name": "foo"}},),
    )
    captured, ctx = _patch_urlopen(body=_minimal_chat_ok_body())
    with ctx:
        chat(request, server)

    payload = json.loads(captured["body"].decode())
    assert payload["top_p"] == 0.9
    assert payload["stop"] == ["<|endoftext|>", "<|im_end|>"]
    assert payload["tools"] == [{"type": "function", "function": {"name": "foo"}}]


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
