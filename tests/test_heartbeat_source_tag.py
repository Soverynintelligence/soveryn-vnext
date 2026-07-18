"""Task 1: thread `source` through the chat path.

Root cause: the heartbeat daemon's `_call_vnext_chat` POSTs to /chat with no
`source`, so every pulse turn lands in conversations with the store's
default `source="direct"` — indistinguishable from a real human turn in the
UI. This test file covers both layers of the fix:

  1. AgentLoop.process_message(..., source=...) tags BOTH the user and the
     assistant turn with the given source, and still defaults to "direct"
     when omitted (human chat behavior unchanged).
  2. The /chat route reads an optional `source` from the request body and
     threads it to AgentLoop.process_message, defaulting to "direct" and
     400-ing on a non-string/empty value.

Harness for (1) mirrors tests/test_agent_loop.py's `_CapturingChat` +
tmp_path ConversationStore pattern. Harness for (2) mirrors
tests/test_app_chat_routes.py's `app_state` fixture (create_app with an
injected fake chat_fn, localhost guard bypassed via app.config).
"""

import json
import sqlite3

import pytest

from soveryn.agents.loop import AgentLoop
from soveryn.app.startup import create_app
from soveryn.config.runtime import ACTIVE_AGENTS
from soveryn.inference.llama_server_client import ChatResponse, StreamChunk
from soveryn.memory.conversation_store import ConversationStore


# ─── Shared fake chat_fn (mirrors _CapturingChat / _FakeChat in the sibling
# test files) ─────────────────────────────────────────────────────────────

class _FakeChat:
    def __init__(self, *, content="pulse ack", finish_reason="stop"):
        self.calls: list[dict] = []
        self.content = content
        self.finish_reason = finish_reason

    def __call__(self, request, server, timeout=60.0):
        self.calls.append({"request": request, "server": server})
        return ChatResponse(
            content=self.content,
            finish_reason=self.finish_reason,
            tool_calls=None,
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            raw={},
        )


# ─── AgentLoop-level: process_message(..., source=...) ──────────────────────

@pytest.fixture
def conv_store(tmp_path):
    return ConversationStore(tmp_path / "conv.db")


@pytest.fixture
def loop_with_fake_chat(conv_store):
    return AgentLoop("aetheria", conv_store, chat_fn=_FakeChat()), conv_store


def test_process_message_tags_both_turns_with_source(loop_with_fake_chat):
    loop, store = loop_with_fake_chat
    sid = store.new_session("aetheria", title="[heartbeat] aetheria")
    loop.process_message(sid, "[HEARTBEAT] pulse", source="heartbeat")
    rows = store.load_history(sid)
    assert [r.role for r in rows] == ["user", "assistant"]
    assert [r.source for r in rows] == ["heartbeat", "heartbeat"]


def test_process_message_defaults_to_direct(loop_with_fake_chat):
    loop, store = loop_with_fake_chat
    sid = store.new_session("aetheria")
    loop.process_message(sid, "hello")
    rows = store.load_history(sid)
    assert [r.role for r in rows] == ["user", "assistant"]
    assert all(r.source == "direct" for r in rows)


def test_process_message_source_verified_via_raw_sql(loop_with_fake_chat):
    """Belt-and-suspenders: verify straight off the conversations table too,
    independent of Turn.source / load_history plumbing."""
    loop, store = loop_with_fake_chat
    sid = store.new_session("aetheria", title="[heartbeat] aetheria")
    loop.process_message(sid, "[HEARTBEAT] pulse", source="heartbeat")
    with sqlite3.connect(str(store.db_path)) as c:
        rows = c.execute(
            "SELECT source FROM conversations WHERE session_id = ? ORDER BY rowid",
            (sid,),
        ).fetchall()
    assert [r[0] for r in rows] == ["heartbeat", "heartbeat"]


class _CapturingStream:
    """Mirrors test_agent_loop_stream.py's fake stream_fn."""

    def __init__(self, *, content="pulse ack", finish_reason="stop"):
        self.calls: list[dict] = []
        self.content = content
        self.finish_reason = finish_reason

    def __call__(self, request, server, timeout=120.0):
        self.calls.append({"request": request, "server": server, "timeout": timeout})
        def _gen():
            yield StreamChunk(delta=self.content, finish_reason=None,
                               tool_calls_delta=None, usage=None, raw={})
            yield StreamChunk(delta="", finish_reason=self.finish_reason,
                               tool_calls_delta=None,
                               usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                               raw={})
        return _gen()


def test_process_message_stream_tags_both_turns_with_source(conv_store):
    """process_message_stream mirrors the sync path's source threading."""
    stream = _CapturingStream()
    loop = AgentLoop("aetheria", conv_store, stream_fn=stream)
    sid = conv_store.new_session("aetheria", title="[heartbeat] aetheria")
    list(loop.process_message_stream(sid, "[HEARTBEAT] pulse", source="heartbeat"))
    rows = conv_store.load_history(sid)
    assert [r.role for r in rows] == ["user", "assistant"]
    assert [r.source for r in rows] == ["heartbeat", "heartbeat"]


def test_process_message_stream_defaults_to_direct(conv_store):
    stream = _CapturingStream()
    loop = AgentLoop("aetheria", conv_store, stream_fn=stream)
    sid = conv_store.new_session("aetheria")
    list(loop.process_message_stream(sid, "hello"))
    rows = conv_store.load_history(sid)
    assert all(r.source == "direct" for r in rows)


# ─── Route-level: /chat threads body["source"] through ──────────────────────

def _err(resp):
    return json.loads(resp.data)["error"]


def _post(client, path, body):
    return client.post(path, data=json.dumps(body), content_type="application/json")


@pytest.fixture
def app_state(tmp_path):
    conv = ConversationStore(tmp_path / "app_conv.db")
    fake_chat = _FakeChat()
    loops = {name: AgentLoop(name, conv, chat_fn=fake_chat) for name in ACTIVE_AGENTS}
    app = create_app(conv_store=conv, agent_loops=loops)
    app.config["SOVERYN_REQUIRE_LOCALHOST"] = False
    return {"app": app, "client": app.test_client(), "conv": conv, "fake_chat": fake_chat}


def _new_session(client, agent="aetheria"):
    resp = _post(client, "/sessions", {"agent": agent})
    return json.loads(resp.data)["session_id"]


def test_chat_route_threads_source_to_persisted_turns(app_state):
    client = app_state["client"]
    sid = _new_session(client, agent="aetheria")
    resp = _post(client, "/chat", {
        "agent": "aetheria", "session_id": sid, "message": "[HEARTBEAT] pulse",
        "source": "heartbeat",
    })
    assert resp.status_code == 200
    rows = app_state["conv"].load_history(sid)
    assert [r.source for r in rows] == ["heartbeat", "heartbeat"]


def test_chat_route_defaults_source_to_direct_when_absent(app_state):
    client = app_state["client"]
    sid = _new_session(client, agent="aetheria")
    resp = _post(client, "/chat", {
        "agent": "aetheria", "session_id": sid, "message": "hello",
    })
    assert resp.status_code == 200
    rows = app_state["conv"].load_history(sid)
    assert all(r.source == "direct" for r in rows)


def test_chat_route_rejects_non_string_source(app_state):
    client = app_state["client"]
    sid = _new_session(client, agent="aetheria")
    for bad in [42, ["heartbeat"], {"x": 1}, ""]:
        resp = _post(client, "/chat", {
            "agent": "aetheria", "session_id": sid, "message": "hi",
            "source": bad,
        })
        assert resp.status_code == 400
        assert _err(resp)["code"] == "invalid_source"


def test_chat_stream_route_threads_source_to_persisted_turns(app_state):
    client = app_state["client"]
    sid = _new_session(client, agent="aetheria")
    resp = _post(client, "/chat_stream", {
        "agent": "aetheria", "session_id": sid, "message": "[HEARTBEAT] pulse",
        "source": "heartbeat",
    })
    assert resp.status_code == 200
    # Accessing .data fully drains the SSE stream (Flask test client), so the
    # assistant turn is saved before we inspect it.
    _ = resp.data
    rows = app_state["conv"].load_history(sid)
    assert [r.source for r in rows] == ["heartbeat", "heartbeat"]


def test_chat_stream_route_rejects_non_string_source(app_state):
    client = app_state["client"]
    sid = _new_session(client, agent="aetheria")
    resp = _post(client, "/chat_stream", {
        "agent": "aetheria", "session_id": sid, "message": "hi",
        "source": 42,
    })
    assert resp.status_code == 400
    assert _err(resp)["code"] == "invalid_source"
