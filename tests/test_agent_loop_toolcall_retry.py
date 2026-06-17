"""AgentLoop._chat retries ONLY the narrow, intermittent failure where the
server rejects the model's own malformed tool-call JSON (HTTP 500 'Failed to
parse tool call arguments'). Every other error propagates unretried.

Context: 2026-06-17, Qwen3.6 on the shared vett-scotty server occasionally
truncated tool-call arguments under heavy read_file use (Vett gained read_file
the same day). Temperature > 0 means a resend almost always yields valid JSON,
so one bad tool call shouldn't surface as a user-facing error.
"""
import pytest

from soveryn.agents.loop import AgentLoop, _TOOLCALL_PARSE_MAX_ATTEMPTS
from soveryn.memory.conversation_store import ConversationStore
from soveryn.platform.inference.llama_server_client import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    LlamaServerError,
)


@pytest.fixture
def conv_store(tmp_path):
    return ConversationStore(tmp_path / "conv.db")


def _ok():
    return ChatResponse(content="ok", finish_reason="stop", tool_calls=None, usage=None, raw={})


def _req():
    return ChatRequest(messages=(ChatMessage(role="user", content="hi"),), model="aetheria")


def _parse_500():
    return LlamaServerError(
        status_code=500,
        detail="Failed to parse tool call arguments as JSON: ... missing closing quote",
        server_name="vett-scotty",
    )


class _Flaky:
    """Raises the queued errors in order, then returns ok responses."""

    def __init__(self, errors):
        self._errors = list(errors)
        self.calls = 0

    def __call__(self, request, server, timeout=60.0):
        self.calls += 1
        if self._errors:
            raise self._errors.pop(0)
        return _ok()


def test_retries_malformed_toolcall_500_then_succeeds(conv_store):
    fake = _Flaky([_parse_500()])  # one bad call, then success
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake)
    resp = loop._chat(_req())
    assert resp.content == "ok"
    assert fake.calls == 2  # retried once, then succeeded


def test_gives_up_after_max_attempts(conv_store):
    fake = _Flaky([_parse_500() for _ in range(_TOOLCALL_PARSE_MAX_ATTEMPTS)])
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake)
    with pytest.raises(LlamaServerError):
        loop._chat(_req())
    assert fake.calls == _TOOLCALL_PARSE_MAX_ATTEMPTS  # bounded, no infinite loop


def test_does_not_retry_unrelated_500(conv_store):
    fake = _Flaky([LlamaServerError(status_code=500, detail="internal boom", server_name="x")])
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake)
    with pytest.raises(LlamaServerError):
        loop._chat(_req())
    assert fake.calls == 1  # a real 500 is not masked by retry


def test_does_not_retry_4xx_even_if_message_matches(conv_store):
    fake = _Flaky([LlamaServerError(
        status_code=400, detail="Failed to parse tool call arguments", server_name="x")])
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake)
    with pytest.raises(LlamaServerError):
        loop._chat(_req())
    assert fake.calls == 1  # only 500 + this message retries
