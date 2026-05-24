"""Tests for soveryn.agents.loop. tmp_path SQLite, injected fake chat_fn."""

import sqlite3
from dataclasses import dataclass
from typing import Any
import pytest

from soveryn.agents.loop import AgentLoop, AgentLoopError
from soveryn.inference.llama_server_client import (
    ChatRequest,
    ChatResponse,
    LlamaServerError,
    LlamaServerTimeout,
)
from soveryn.inference.routing import RoutingError
from soveryn.memory.conversation_store import ConversationStore


# ─── Fixtures + fakes ────────────────────────────────────────────────────────

@pytest.fixture
def conv_store(tmp_path):
    return ConversationStore(tmp_path / "conv.db")


class _CapturingChat:
    """Fake chat_fn that records every call and returns a configured response."""

    def __init__(self, *, content="OK", finish_reason="stop", raise_exc=None):
        self.calls: list[dict] = []
        self.content = content
        self.finish_reason = finish_reason
        self.raise_exc = raise_exc

    def __call__(self, request, server, timeout=60.0):
        self.calls.append({
            "request": request,
            "server": server,
            "timeout": timeout,
        })
        if self.raise_exc is not None:
            raise self.raise_exc
        return ChatResponse(
            content=self.content,
            finish_reason=self.finish_reason,
            tool_calls=None,
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            raw={"choices": [{"message": {"content": self.content}}]},
        )


# ─── Constructor: routing at construction ────────────────────────────────────

def test_construction_routes_aetheria_to_8085(conv_store):
    loop = AgentLoop("aetheria", conv_store, chat_fn=_CapturingChat())
    assert loop.server.port == 8085
    assert loop.agent_name == "aetheria"


def test_construction_routes_vett_to_8084(conv_store):
    loop = AgentLoop("vett", conv_store, chat_fn=_CapturingChat())
    assert loop.server.port == 8084


def test_construction_normalizes_name_case(conv_store):
    loop = AgentLoop("  Aetheria  ", conv_store, chat_fn=_CapturingChat())
    assert loop.agent_name == "aetheria"
    assert loop.server.name == "aetheria_primary"


@pytest.mark.parametrize("name", [
    "scout", "vision", "tinker", "forge",
    "ares_llm", "aetheria_public", "telegram", "chromadb",
])
def test_construction_rejects_retired_agents(conv_store, name):
    with pytest.raises(RoutingError, match="retired"):
        AgentLoop(name, conv_store, chat_fn=_CapturingChat())


def test_construction_rejects_unknown_agent(conv_store):
    with pytest.raises(RoutingError, match="No route"):
        AgentLoop("fnord", conv_store, chat_fn=_CapturingChat())


def test_construction_failure_never_calls_chat(conv_store):
    fake = _CapturingChat()
    with pytest.raises(RoutingError):
        AgentLoop("scout", conv_store, chat_fn=fake)
    assert fake.calls == []


# ─── Session validation (constraint 8) ───────────────────────────────────────

def test_missing_session_raises_before_chat(conv_store):
    fake = _CapturingChat()
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake)
    with pytest.raises(AgentLoopError, match="does not exist"):
        loop.process_message("not-a-real-session", "hi")
    # Constraint 8: no chat dispatched
    assert fake.calls == []
    # Constraint 8: no user turn saved (session doesn't exist anyway,
    # but a defensive INSERT would still write a row keyed on the bad id)
    with sqlite3.connect(str(conv_store.db_path)) as c:
        rows = c.execute(
            "SELECT COUNT(*) FROM conversations WHERE session_id = ?",
            ("not-a-real-session",),
        ).fetchone()
    assert rows[0] == 0


def test_session_for_other_agent_raises_before_chat(conv_store):
    """A Vett session can't be used by an Aetheria loop."""
    vett_session = conv_store.new_session("vett")
    fake = _CapturingChat()
    aetheria_loop = AgentLoop("aetheria", conv_store, chat_fn=fake)
    with pytest.raises(AgentLoopError, match="belongs to agent 'vett'"):
        aetheria_loop.process_message(vett_session, "hi")
    assert fake.calls == []
    # No user turn snuck into the wrong session
    assert conv_store.load_history(vett_session) == ()


# ─── Happy path ──────────────────────────────────────────────────────────────

def test_happy_path_returns_raw_chat_response(conv_store):
    sid = conv_store.new_session("aetheria")
    fake = _CapturingChat(content="hi back")
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake)
    response = loop.process_message(sid, "hello")
    assert isinstance(response, ChatResponse)
    assert response.content == "hi back"
    assert response.finish_reason == "stop"


def test_user_turn_then_assistant_turn_saved(conv_store):
    sid = conv_store.new_session("aetheria")
    fake = _CapturingChat(content="response text")
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake)
    loop.process_message(sid, "user said this")
    history = conv_store.load_history(sid)
    assert len(history) == 2
    assert history[0].role == "user"
    assert history[0].content == "user said this"
    assert history[1].role == "assistant"
    assert history[1].content == "response text"


def test_assistant_turn_stores_content_only_not_raw_metadata(conv_store):
    """Constraint 4: response.tool_calls / usage / raw must NOT land in conversations."""
    sid = conv_store.new_session("aetheria")
    fake = _CapturingChat(content="just the text")
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake)
    loop.process_message(sid, "hi")
    history = conv_store.load_history(sid)
    assistant_turn = history[1]
    assert assistant_turn.content == "just the text"
    # The saved content must not include any serialized metadata
    assert "tool_calls" not in assistant_turn.content
    assert "usage" not in assistant_turn.content
    assert "{" not in assistant_turn.content


def test_history_passed_to_chat_as_immutable_tuple(conv_store):
    """Constraint 7."""
    sid = conv_store.new_session("aetheria")
    fake = _CapturingChat()
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake)
    loop.process_message(sid, "msg one")
    request = fake.calls[0]["request"]
    assert isinstance(request, ChatRequest)
    assert isinstance(request.messages, tuple)
    with pytest.raises((TypeError, AttributeError)):
        request.messages.append(None)  # tuple has no .append


def test_history_includes_prior_turns_on_subsequent_calls(conv_store):
    """Multi-turn: each process_message should see the full prior history."""
    sid = conv_store.new_session("aetheria")
    fake = _CapturingChat(content="reply-1")
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake)
    loop.process_message(sid, "turn-1")
    fake.content = "reply-2"
    loop.process_message(sid, "turn-2")
    # The second call's request should carry: u1, a1, u2 (3 messages)
    second_request = fake.calls[1]["request"]
    contents = [m.content for m in second_request.messages]
    assert contents == ["turn-1", "reply-1", "turn-2"]


def test_routing_resolved_once_at_construction(conv_store):
    """Constraint 1: server is bound at __init__; the same one is passed to every chat call."""
    sid = conv_store.new_session("aetheria")
    fake = _CapturingChat()
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake)
    loop.process_message(sid, "a")
    loop.process_message(sid, "b")
    loop.process_message(sid, "c")
    servers = [c["server"] for c in fake.calls]
    assert all(s is loop.server for s in servers)


# ─── Failure modes ───────────────────────────────────────────────────────────

def test_chat_failure_leaves_user_turn_saved(conv_store):
    """Constraint 6: honest state. If chat blows up after we saved the user turn,
    that user turn stays in the DB. No rollback magic."""
    sid = conv_store.new_session("aetheria")
    err = LlamaServerError(status_code=500, detail="boom", server_name="vett_scotty_shared")
    fake = _CapturingChat(raise_exc=err)
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake)
    with pytest.raises(LlamaServerError):
        loop.process_message(sid, "user message that survives")
    history = conv_store.load_history(sid)
    assert len(history) == 1
    assert history[0].role == "user"
    assert history[0].content == "user message that survives"


def test_chat_timeout_propagates_and_user_turn_stays(conv_store):
    sid = conv_store.new_session("aetheria")
    fake = _CapturingChat(raise_exc=LlamaServerTimeout("vett_scotty_shared", 60.0))
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake)
    with pytest.raises(LlamaServerTimeout):
        loop.process_message(sid, "user")
    history = conv_store.load_history(sid)
    assert len(history) == 1 and history[0].role == "user"


def test_assistant_save_failure_propagates(conv_store, monkeypatch):
    """Constraint 5: if the assistant-turn save fails (DB locked, FK violation,
    whatever), the error must propagate. Don't pretend success."""
    sid = conv_store.new_session("aetheria")
    fake = _CapturingChat(content="will fail to save")
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake)

    # Make the SECOND save_turn call raise (assistant save).
    original_save = conv_store.save_turn
    call_count = {"n": 0}
    def flaky_save(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 2:  # the assistant turn
            raise sqlite3.OperationalError("simulated DB write failure")
        return original_save(*args, **kwargs)
    monkeypatch.setattr(conv_store, "save_turn", flaky_save)

    with pytest.raises(sqlite3.OperationalError, match="simulated DB write failure"):
        loop.process_message(sid, "hi")

    # User turn DID save (the first call). Assistant turn did NOT.
    history = conv_store.load_history(sid)
    assert len(history) == 1
    assert history[0].role == "user"
