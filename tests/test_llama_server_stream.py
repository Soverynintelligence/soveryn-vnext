"""Tests for soveryn.inference.llama_server_client.chat_stream.

Mocks urllib.request.urlopen to return canned SSE bodies. No real network.
"""

import io
import json
from unittest.mock import patch
import pytest

from soveryn.inference.llama_server_client import (
    ChatMessage, ChatRequest, LlamaServerError, LlamaServerTimeout,
    SSE_DATA_PREFIX, SSE_DONE_MARKER, StreamChunk, chat_stream,
)


def _server():
    from soveryn.config.runtime import MODEL_SERVERS
    return next(s for s in MODEL_SERVERS if s.name == "vett_scotty_shared")


def _request():
    return ChatRequest(
        messages=(ChatMessage(role="user", content="hi"),),
        model="vett_scotty_shared",
    )


class _FakeSSEResponse:
    """File-like that yields lines on iteration; supports `with` + .close()."""
    def __init__(self, lines: list[bytes]):
        self._lines = list(lines)
    def __iter__(self):
        return iter(self._lines)
    def close(self):
        pass
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


def _data_line(payload) -> bytes:
    return f"data: {json.dumps(payload)}\n".encode()


def _done_line() -> bytes:
    return b"data: [DONE]\n"


# ─── Happy path ──────────────────────────────────────────────────────────────

def test_chat_stream_payload_includes_repetition_penalty():
    captured = {}
    body = [
        _data_line({"choices": [{"delta": {"content": "hi"}, "index": 0, "finish_reason": None}]}),
        _data_line({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}}),
        _done_line(),
    ]

    def fake_urlopen(req, timeout=None):
        captured["req"] = req
        captured["timeout"] = timeout
        return _FakeSSEResponse(body)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        chunks = list(chat_stream(_request(), _server()))

    payload = json.loads(captured["req"].data.decode())
    assert payload["repetition_penalty"] == 1.1
    assert [c.delta for c in chunks] == ["hi", ""]


def test_chat_stream_yields_content_deltas():
    body = [
        _data_line({"choices": [{"delta": {"content": "hi"}, "index": 0, "finish_reason": None}]}),
        _data_line({"choices": [{"delta": {"content": " there"}, "index": 0, "finish_reason": None}]}),
        _data_line({"choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}}),
        _done_line(),
    ]
    with patch("urllib.request.urlopen", return_value=_FakeSSEResponse(body)):
        chunks = list(chat_stream(_request(), _server()))
    assert [c.delta for c in chunks] == ["hi", " there", ""]
    assert chunks[-1].finish_reason == "stop"
    assert chunks[-1].usage["total_tokens"] == 3


def test_chat_stream_done_marker_terminates_cleanly():
    """`data: [DONE]` ends iteration without yielding."""
    body = [
        _data_line({"choices": [{"delta": {"content": "x"}, "finish_reason": "stop"}]}),
        _done_line(),
        _data_line({"choices": [{"delta": {"content": "should not appear"}}]}),  # post-DONE junk
    ]
    with patch("urllib.request.urlopen", return_value=_FakeSSEResponse(body)):
        chunks = list(chat_stream(_request(), _server()))
    assert len(chunks) == 1
    assert chunks[0].delta == "x"


def test_chat_stream_skips_blank_lines_and_comments():
    body = [
        b"\n",
        b": ping comment\n",
        _data_line({"choices": [{"delta": {"content": "a"}, "finish_reason": None}]}),
        b"\n",
        _data_line({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
        _done_line(),
    ]
    with patch("urllib.request.urlopen", return_value=_FakeSSEResponse(body)):
        chunks = list(chat_stream(_request(), _server()))
    assert [c.delta for c in chunks] == ["a", ""]


def test_chat_stream_skips_non_terminal_malformed():
    """Garbage data line that doesn't look terminal → skip silently."""
    body = [
        b"data: this is not json but no finish or done marker\n",
        _data_line({"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}),
        _done_line(),
    ]
    with patch("urllib.request.urlopen", return_value=_FakeSSEResponse(body)):
        chunks = list(chat_stream(_request(), _server()))
    assert [c.delta for c in chunks] == ["ok"]


def test_chat_stream_raises_on_malformed_terminal_chunk():
    """A malformed line that contains 'finish_reason' → raise (Jon constraint 7)."""
    body = [
        b'data: {"choices": [{"delta": {}, "finish_reason": "stop\n',  # truncated, contains finish_reason
        _done_line(),
    ]
    with patch("urllib.request.urlopen", return_value=_FakeSSEResponse(body)):
        with pytest.raises(LlamaServerError, match="malformed terminal SSE chunk"):
            list(chat_stream(_request(), _server()))


def test_chat_stream_raises_on_malformed_done_line():
    body = [
        b"data: [DONE\n",  # contains [DONE] substring but not the clean marker
    ]
    with patch("urllib.request.urlopen", return_value=_FakeSSEResponse(body)):
        with pytest.raises(LlamaServerError, match="malformed terminal SSE chunk"):
            list(chat_stream(_request(), _server()))


# ─── Network failure modes ───────────────────────────────────────────────────

def test_chat_stream_http_error_raises_llama_server_error():
    import urllib.error
    err = urllib.error.HTTPError("u", 500, "boom", {}, io.BytesIO(b"server crashed"))
    with patch("urllib.request.urlopen", side_effect=err):
        with pytest.raises(LlamaServerError) as ei:
            list(chat_stream(_request(), _server()))
    assert ei.value.status_code == 500


def test_chat_stream_timeout_raises_llama_server_timeout():
    import socket
    with patch("urllib.request.urlopen", side_effect=socket.timeout()):
        with pytest.raises(LlamaServerTimeout):
            list(chat_stream(_request(), _server()))


# ─── Tool call deltas pass through ───────────────────────────────────────────

def test_chat_stream_emits_tool_calls_delta():
    body = [
        _data_line({"choices": [{"delta": {
            "tool_calls": [{"index": 0, "id": "c1", "type": "function",
                            "function": {"name": "foo", "arguments": ""}}]
        }, "finish_reason": None}]}),
        _data_line({"choices": [{"delta": {
            "tool_calls": [{"index": 0, "function": {"arguments": "{}"}}]
        }, "finish_reason": None}]}),
        _data_line({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}),
        _done_line(),
    ]
    with patch("urllib.request.urlopen", return_value=_FakeSSEResponse(body)):
        chunks = list(chat_stream(_request(), _server()))
    tc_chunks = [c for c in chunks if c.tool_calls_delta]
    assert len(tc_chunks) == 2
    assert chunks[-1].finish_reason == "tool_calls"


def test_chat_stream_preserves_raw_chunks():
    """StreamChunk.raw must carry the full upstream dict."""
    body = [
        _data_line({"choices": [{"delta": {"content": "x"}, "finish_reason": None}],
                    "id": "chat-abc", "model": "vett_scotty_shared"}),
        _data_line({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
        _done_line(),
    ]
    with patch("urllib.request.urlopen", return_value=_FakeSSEResponse(body)):
        chunks = list(chat_stream(_request(), _server()))
    assert chunks[0].raw.get("id") == "chat-abc"
    assert chunks[0].raw.get("model") == "vett_scotty_shared"
