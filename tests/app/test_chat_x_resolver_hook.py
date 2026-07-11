"""Tests for the chat-path pre-turn X-approval resolver hook (Task 8).

Both /chat and /chat_stream must run `maybe_resolve_x_approval` BEFORE the
normal AgentLoop turn — the staged post is keyed on the AGENT ("aetheria"),
not the session, so a bare "yes" in Jon's primary thread must publish a
post that was staged during a heartbeat wake. A clear affirm publishes and
skips her normal conversational turn entirely; anything else (unrelated,
edit, decline, a [HEARTBEAT] brief, or agent != aetheria) is a no-op for
publishing and her normal turn runs untouched.
"""

from __future__ import annotations

import json

import pytest

from soveryn.agents.loop import AgentLoop
from soveryn.agents.presence.staged_store import StagedStore
from soveryn.app.startup import create_app
from soveryn.config.runtime import ACTIVE_AGENTS
from soveryn.inference.llama_server_client import ChatResponse, StreamChunk
from soveryn.memory.conversation_store import ConversationStore


# ─── Fakes ────────────────────────────────────────────────────────────────

class _FakeChat:
    """Records calls — a call means the normal /chat turn ran."""

    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, request, server, timeout=60.0):
        self.calls.append({"request": request, "server": server})
        return ChatResponse(
            content="normal turn ran", finish_reason="stop",
            tool_calls=None, usage=None, raw={},
        )


class _FakeStream:
    """Records calls — a call means the normal /chat_stream turn ran."""

    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, request, server, timeout=120.0):
        self.calls.append({"request": request, "server": server})

        def _g():
            yield StreamChunk(delta="normal", finish_reason=None,
                               tool_calls_delta=None, usage=None, raw={})
            yield StreamChunk(delta="", finish_reason="stop",
                               tool_calls_delta=None, usage=None, raw={})

        return _g()


class _Recorder:
    """Fake x_publisher_fn / x_memory_fn / x_rejection_fn, call-recording."""

    def __init__(self, publish_result=None):
        self.publish_calls: list[tuple[str, str | None]] = []
        self.memory_calls: list = []
        self.rejection_calls: list[tuple] = []
        self._publish_result = publish_result or {
            "id": "999", "url": "https://x.com/i/web/status/999",
        }

    def publisher_fn(self, text, reply_to):
        self.publish_calls.append((text, reply_to))
        return self._publish_result

    def memory_fn(self, post, result=None):
        self.memory_calls.append((post, result))

    def rejection_fn(self, post, reason=None):
        self.rejection_calls.append((post, reason))


# ─── Harness ──────────────────────────────────────────────────────────────

@pytest.fixture
def app_state(tmp_path):
    """A fully wired app (fake chat_fn/stream_fn — no network) with the X
    resolver deps injected onto app.extensions["soveryn"] the way
    soveryn/app/startup.py wires them in production (Part A)."""
    conv = ConversationStore(tmp_path / "conv.db")
    fake_chat = _FakeChat()
    fake_stream = _FakeStream()
    loops = {
        name: AgentLoop(name, conv, chat_fn=fake_chat, stream_fn=fake_stream)
        for name in ACTIVE_AGENTS
    }
    app = create_app(conv_store=conv, agent_loops=loops)
    app.config["SOVERYN_REQUIRE_LOCALHOST"] = False

    staged = StagedStore(tmp_path / "staged.db")
    rec = _Recorder()
    app.extensions["soveryn"]["x_staged"] = staged
    app.extensions["soveryn"]["x_publisher_fn"] = rec.publisher_fn
    app.extensions["soveryn"]["x_memory_fn"] = rec.memory_fn
    app.extensions["soveryn"]["x_rejection_fn"] = rec.rejection_fn

    return {
        "app": app, "client": app.test_client(), "conv": conv,
        "fake_chat": fake_chat, "fake_stream": fake_stream,
        "staged": staged, "rec": rec,
    }


def _new_session(client, agent):
    resp = client.post("/sessions", data=json.dumps({"agent": agent}),
                        content_type="application/json")
    return json.loads(resp.data)["session_id"]


def _post(client, path, body):
    return client.post(path, data=json.dumps(body), content_type="application/json")


def _parse_sse(data: bytes) -> list[dict]:
    out = []
    for line in data.decode("utf-8").splitlines():
        if line.startswith("data: "):
            out.append(json.loads(line[len("data: "):]))
    return out


# ─── /chat ────────────────────────────────────────────────────────────────

def test_chat_affirm_publishes_and_skips_normal_turn(app_state):
    sid = _new_session(app_state["client"], "aetheria")
    app_state["staged"].stage(agent="aetheria", text="draft post", reply_to=None,
                               now="2026-07-11T10:00:00")

    resp = _post(app_state["client"], "/chat",
                 {"agent": "aetheria", "session_id": sid, "message": "post it"})

    assert resp.status_code == 200
    payload = json.loads(resp.data)
    assert payload["x_resolution"]["action"] == "published"
    assert "https://x.com" in payload["x_resolution"]["note"]
    assert app_state["rec"].publish_calls == [("draft post", None)]
    assert len(app_state["rec"].memory_calls) == 1
    assert app_state["fake_chat"].calls == []  # normal turn did NOT run
    assert app_state["staged"].pending("aetheria") is None


def test_chat_normal_message_nothing_staged_runs_loop(app_state):
    sid = _new_session(app_state["client"], "aetheria")

    resp = _post(app_state["client"], "/chat",
                 {"agent": "aetheria", "session_id": sid, "message": "hey there"})

    assert resp.status_code == 200
    payload = json.loads(resp.data)
    assert "x_resolution" not in payload
    assert payload["content"] == "normal turn ran"
    assert len(app_state["fake_chat"].calls) == 1
    assert app_state["rec"].publish_calls == []


def test_chat_heartbeat_message_with_pending_does_not_publish(app_state):
    sid = _new_session(app_state["client"], "aetheria")
    app_state["staged"].stage(agent="aetheria", text="draft post", reply_to=None,
                               now="2026-07-11T10:00:00")

    resp = _post(app_state["client"], "/chat",
                 {"agent": "aetheria", "session_id": sid,
                  "message": "[HEARTBEAT]\nRoutine wake — check the board."})

    assert resp.status_code == 200
    payload = json.loads(resp.data)
    assert "x_resolution" not in payload
    assert app_state["rec"].publish_calls == []
    assert len(app_state["fake_chat"].calls) == 1  # her normal wake ran
    assert app_state["staged"].pending("aetheria") is not None  # still proposed


def test_chat_non_aetheria_agent_hook_is_noop(app_state):
    # Stage a post for aetheria (agent-slot keyed) — a "yes" from vett's
    # session must NOT resolve it; the hook only applies to agent=="aetheria".
    sid = _new_session(app_state["client"], "vett")
    app_state["staged"].stage(agent="aetheria", text="draft post", reply_to=None,
                               now="2026-07-11T10:00:00")

    resp = _post(app_state["client"], "/chat",
                 {"agent": "vett", "session_id": sid, "message": "yes"})

    assert resp.status_code == 200
    payload = json.loads(resp.data)
    assert "x_resolution" not in payload
    assert app_state["rec"].publish_calls == []
    assert len(app_state["fake_chat"].calls) == 1  # vett's normal turn ran
    assert app_state["staged"].pending("aetheria") is not None  # untouched


def test_chat_decline_marks_rejected_no_publish(app_state):
    sid = _new_session(app_state["client"], "aetheria")
    app_state["staged"].stage(agent="aetheria", text="draft post", reply_to=None,
                               now="2026-07-11T10:00:00")

    resp = _post(app_state["client"], "/chat",
                 {"agent": "aetheria", "session_id": sid, "message": "no"})

    assert resp.status_code == 200
    payload = json.loads(resp.data)
    assert payload["x_resolution"]["action"] == "declined"
    assert app_state["rec"].publish_calls == []
    assert len(app_state["rec"].rejection_calls) == 1
    assert app_state["fake_chat"].calls == []  # normal turn did NOT run
    assert app_state["staged"].pending("aetheria") is None


def test_chat_missing_x_state_keys_hook_is_noop(tmp_path):
    """No X deps wired at all (e.g. a fixture that never touched
    app.extensions) — the hook must not KeyError; normal turn runs."""
    conv = ConversationStore(tmp_path / "conv2.db")
    fake_chat = _FakeChat()
    loops = {name: AgentLoop(name, conv, chat_fn=fake_chat) for name in ACTIVE_AGENTS}
    app = create_app(conv_store=conv, agent_loops=loops)
    app.config["SOVERYN_REQUIRE_LOCALHOST"] = False
    client = app.test_client()
    sid = _new_session(client, "aetheria")

    resp = _post(client, "/chat", {"agent": "aetheria", "session_id": sid, "message": "yes"})

    assert resp.status_code == 200
    payload = json.loads(resp.data)
    assert "x_resolution" not in payload
    assert len(fake_chat.calls) == 1


# ─── /chat_stream ────────────────────────────────────────────────────────

def test_chat_stream_affirm_publishes_and_skips_normal_turn(app_state):
    sid = _new_session(app_state["client"], "aetheria")
    app_state["staged"].stage(agent="aetheria", text="draft post", reply_to=None,
                               now="2026-07-11T10:00:00")

    resp = _post(app_state["client"], "/chat_stream",
                 {"agent": "aetheria", "session_id": sid, "message": "post it"})

    assert resp.status_code == 200
    events = _parse_sse(resp.data)
    assert len(events) == 1
    assert events[0]["type"] == "x_resolution"
    assert events[0]["action"] == "published"
    assert app_state["rec"].publish_calls == [("draft post", None)]
    assert app_state["fake_stream"].calls == []  # normal turn did NOT run
    assert app_state["staged"].pending("aetheria") is None


def test_chat_stream_normal_message_nothing_staged_runs_loop(app_state):
    sid = _new_session(app_state["client"], "aetheria")

    resp = _post(app_state["client"], "/chat_stream",
                 {"agent": "aetheria", "session_id": sid, "message": "hey there"})

    assert resp.status_code == 200
    events = _parse_sse(resp.data)
    assert all(e["type"] != "x_resolution" for e in events)
    assert len(app_state["fake_stream"].calls) == 1
    assert app_state["rec"].publish_calls == []


def test_chat_stream_heartbeat_message_with_pending_does_not_publish(app_state):
    sid = _new_session(app_state["client"], "aetheria")
    app_state["staged"].stage(agent="aetheria", text="draft post", reply_to=None,
                               now="2026-07-11T10:00:00")

    resp = _post(app_state["client"], "/chat_stream",
                 {"agent": "aetheria", "session_id": sid,
                  "message": "[HEARTBEAT]\nRoutine wake — check the board."})

    assert resp.status_code == 200
    events = _parse_sse(resp.data)
    assert all(e["type"] != "x_resolution" for e in events)
    assert app_state["rec"].publish_calls == []
    assert len(app_state["fake_stream"].calls) == 1
    assert app_state["staged"].pending("aetheria") is not None


def test_chat_stream_affirm_emits_done_event_to_close_spinner(app_state):
    """The /chat_stream approval path must terminate the SSE stream with a
    'done' frame — otherwise the UI's thinking spinner hangs forever (the
    resolver short-circuits the normal turn, so no DoneEvent arrives)."""
    sid = _new_session(app_state["client"], "aetheria")
    app_state["staged"].stage(agent="aetheria", text="draft post", reply_to=None,
                               now="2026-07-11T10:00:00")

    resp = _post(app_state["client"], "/chat_stream",
                 {"agent": "aetheria", "session_id": sid, "message": "post it"})

    assert resp.status_code == 200
    events = _parse_sse(resp.data)
    types = [e["type"] for e in events]
    assert "x_resolution" in types
    assert "done" in types, f"stream did not close with a done event: {types}"
    # the done frame carries the resolution note as content
    done = next(e for e in events if e["type"] == "done")
    assert "posted to X" in (done.get("content") or "")
    assert app_state["rec"].publish_calls == [("draft post", None)]
