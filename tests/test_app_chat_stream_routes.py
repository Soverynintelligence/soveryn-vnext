"""Tests for POST /chat_stream — Flask test_client SSE."""

import json
import pytest

from soveryn.agents.loop import AgentLoop
from soveryn.app.startup import create_app
from soveryn.config.runtime import ACTIVE_AGENTS
from soveryn.inference.llama_server_client import StreamChunk, LlamaServerError, ChatResponse
from soveryn.memory.conversation_store import ConversationStore


class _StreamFn:
    def __init__(self, chunks=None, raise_exc=None):
        self.chunks = chunks or []
        self.raise_exc = raise_exc
        self.calls = []
    def __call__(self, request, server, timeout=120.0):
        self.calls.append({"request": request, "server": server})
        if self.raise_exc is not None:
            raise self.raise_exc
        def _g():
            for c in self.chunks:
                yield c
        return _g()


def _chunks(*specs):
    return [StreamChunk(delta=s[0], finish_reason=s[1] if len(s) > 1 else None,
                        tool_calls_delta=None,
                        usage=s[2] if len(s) > 2 else None, raw={})
            for s in specs]


@pytest.fixture
def app_state(tmp_path):
    conv = ConversationStore(tmp_path / "conv.db")
    stream = _StreamFn(chunks=_chunks(("hi", None), (" there", None), ("", "stop")))
    # Also need a fake chat_fn for the sync /chat path
    fake_chat = lambda req, server, timeout=60: ChatResponse(
        content="", finish_reason="stop", tool_calls=None, usage=None, raw={})
    loops = {n: AgentLoop(n, conv, chat_fn=fake_chat, stream_fn=stream)
             for n in ACTIVE_AGENTS}
    app = create_app(conv_store=conv, agent_loops=loops)
    app.config["SOVERYN_REQUIRE_LOCALHOST"] = False
    return {"app": app, "client": app.test_client(), "conv": conv,
            "stream": stream, "loops": loops}


def _post_stream(client, body):
    return client.post("/chat_stream",
                       data=json.dumps(body),
                       content_type="application/json")


def _parse_sse(data: bytes) -> list[dict]:
    """Parse SSE-framed response body into list of JSON dicts."""
    out = []
    for line in data.decode("utf-8").splitlines():
        if line.startswith("data: "):
            out.append(json.loads(line[len("data: "):]))
    return out


# ─── Setup errors are JSON 4xx/5xx, not SSE ──────────────────────────────────

def test_chat_stream_missing_session_returns_json_404(app_state):
    resp = _post_stream(app_state["client"],
                        {"agent": "aetheria", "session_id": "ghost", "message": "hi"})
    assert resp.status_code == 404
    assert resp.content_type.startswith("application/json")
    assert json.loads(resp.data)["error"]["code"] == "missing_session"
    assert app_state["stream"].calls == []  # never opened


def test_chat_stream_unknown_agent_returns_json_400(app_state):
    resp = _post_stream(app_state["client"],
                        {"agent": "fnord", "session_id": "x", "message": "hi"})
    assert resp.status_code == 400
    assert resp.content_type.startswith("application/json")


def test_chat_stream_retired_agent_returns_json_400(app_state):
    resp = _post_stream(app_state["client"],
                        {"agent": "scout", "session_id": "x", "message": "hi"})
    assert resp.status_code == 400
    assert json.loads(resp.data)["error"]["code"] == "retired_agent"


def test_chat_stream_empty_message_returns_json_400(app_state):
    # Create a session first
    s = app_state["client"].post("/sessions",
                                 data=json.dumps({"agent": "aetheria"}),
                                 content_type="application/json")
    sid = json.loads(s.data)["session_id"]
    resp = _post_stream(app_state["client"],
                        {"agent": "aetheria", "session_id": sid, "message": "  "})
    assert resp.status_code == 400
    assert json.loads(resp.data)["error"]["code"] == "invalid_message"


def test_chat_stream_session_agent_mismatch_returns_json_409(app_state):
    s = app_state["client"].post("/sessions",
                                 data=json.dumps({"agent": "vett"}),
                                 content_type="application/json")
    sid = json.loads(s.data)["session_id"]
    resp = _post_stream(app_state["client"],
                        {"agent": "aetheria", "session_id": sid, "message": "hi"})
    assert resp.status_code == 409
    assert json.loads(resp.data)["error"]["code"] == "session_agent_mismatch"


def test_chat_stream_upstream_setup_failure_returns_json_502(tmp_path):
    conv = ConversationStore(tmp_path / "conv.db")
    stream = _StreamFn(raise_exc=LlamaServerError(500, "boom", "aetheria_primary"))
    fake_chat = lambda req, server, timeout=60: ChatResponse(
        content="", finish_reason="stop", tool_calls=None, usage=None, raw={})
    loops = {n: AgentLoop(n, conv, chat_fn=fake_chat, stream_fn=stream) for n in ACTIVE_AGENTS}
    app = create_app(conv_store=conv, agent_loops=loops)
    app.config["SOVERYN_REQUIRE_LOCALHOST"] = False
    client = app.test_client()
    s = client.post("/sessions",
                    data=json.dumps({"agent": "aetheria"}),
                    content_type="application/json")
    sid = json.loads(s.data)["session_id"]
    resp = _post_stream(client,
                        {"agent": "aetheria", "session_id": sid, "message": "hi"})
    assert resp.status_code == 502
    assert json.loads(resp.data)["error"]["code"] == "chat_server_error"


# ─── Happy SSE flow ──────────────────────────────────────────────────────────

def test_chat_stream_happy_returns_sse_with_token_and_done(app_state):
    s = app_state["client"].post("/sessions",
                                 data=json.dumps({"agent": "aetheria"}),
                                 content_type="application/json")
    sid = json.loads(s.data)["session_id"]
    resp = _post_stream(app_state["client"],
                        {"agent": "aetheria", "session_id": sid, "message": "hi"})
    assert resp.status_code == 200
    assert resp.content_type.startswith("text/event-stream")
    assert resp.headers.get("Cache-Control") == "no-cache"
    assert resp.headers.get("X-Accel-Buffering") == "no"

    events = _parse_sse(resp.data)
    # token, token, done
    assert events[0] == {"type": "token", "delta": "hi"}
    assert events[1] == {"type": "token", "delta": " there"}
    assert events[-1]["type"] == "done"
    assert events[-1]["content"] == "hi there"
    assert events[-1]["finish_reason"] == "stop"


def test_chat_stream_serializes_error_events(tmp_path):
    """Mid-stream error → SSE 200 with a final {type:error,...} event."""
    conv = ConversationStore(tmp_path / "conv.db")
    # Yield one chunk, then raise mid-stream
    class _MidFail:
        calls = []
        def __call__(self, request, server, timeout=120.0):
            self.calls.append({})
            def _g():
                yield StreamChunk(delta="partial", finish_reason=None,
                                  tool_calls_delta=None, usage=None, raw={})
                raise LlamaServerError(500, "mid-stream crash", "aetheria_primary")
            return _g()
    stream = _MidFail()
    fake_chat = lambda req, server, timeout=60: ChatResponse(
        content="", finish_reason="stop", tool_calls=None, usage=None, raw={})
    loops = {n: AgentLoop(n, conv, chat_fn=fake_chat, stream_fn=stream) for n in ACTIVE_AGENTS}
    app = create_app(conv_store=conv, agent_loops=loops)
    app.config["SOVERYN_REQUIRE_LOCALHOST"] = False
    client = app.test_client()
    s = client.post("/sessions",
                    data=json.dumps({"agent": "aetheria"}),
                    content_type="application/json")
    sid = json.loads(s.data)["session_id"]
    resp = _post_stream(client,
                        {"agent": "aetheria", "session_id": sid, "message": "hi"})
    # Stream was opened (status 200) — error appears AS an SSE event
    assert resp.status_code == 200
    events = _parse_sse(resp.data)
    assert events[0]["type"] == "token"
    assert events[-1]["type"] == "error"
    assert events[-1]["code"] == "chat_server_error"


# ─── /chat_stream attachments (vision) ───────────────────────────────────────


def _new_session(client, agent="aetheria"):
    s = client.post("/sessions",
                    data=json.dumps({"agent": agent}),
                    content_type="application/json")
    return json.loads(s.data)["session_id"]


def test_chat_stream_accepts_attachments_passes_to_loop(app_state):
    """Happy path: attachments plumbed through to the stream_fn's ChatRequest."""
    img = "data:image/jpeg;base64,AAAA"
    client = app_state["client"]
    sid = _new_session(client, agent="aetheria")
    resp = _post_stream(client, {
        "agent": "aetheria", "session_id": sid,
        "message": "what's this?",
        "attachments": [img],
    })
    assert resp.status_code == 200
    # Drain the SSE response to ensure events are well-formed
    events = _parse_sse(resp.data)
    assert any(e["type"] == "token" for e in events)
    assert events[-1]["type"] == "done"
    # Verify attachments reached the loop via the captured ChatRequest:
    captured = app_state["stream"].calls[-1]["request"]
    last_user = captured.messages[-1]
    assert isinstance(last_user.content, list)
    assert any(p.get("type") == "image_url" and p["image_url"]["url"] == img
               for p in last_user.content)


def test_chat_stream_rejects_non_image_data_url(app_state):
    client = app_state["client"]
    sid = _new_session(client, agent="aetheria")
    resp = _post_stream(client, {
        "agent": "aetheria", "session_id": sid, "message": "hi",
        "attachments": ["data:application/pdf;base64,AAAA"],
    })
    assert resp.status_code == 400
    assert resp.content_type.startswith("application/json")
    assert json.loads(resp.data)["error"]["code"] == "invalid_attachments"
    assert app_state["stream"].calls == []  # loop never opened


def test_chat_stream_rejects_oversized_attachment(app_state):
    client = app_state["client"]
    sid = _new_session(client, agent="aetheria")
    big = "data:image/jpeg;base64," + ("A" * 33_500_000)
    resp = _post_stream(client, {
        "agent": "aetheria", "session_id": sid, "message": "hi",
        "attachments": [big],
    })
    assert resp.status_code == 400
    assert json.loads(resp.data)["error"]["code"] == "invalid_attachments"
    assert app_state["stream"].calls == []


@pytest.mark.parametrize("agent", ["vett", "scotty"])
def test_chat_stream_accepts_attachments_on_vision_capable_agents(app_state, agent):
    """Vett + Scotty share the vett-scotty mmproj server — their attachments
    must stream through, not 400 as Aetheria-only. (Route-level rejection of a
    genuinely non-vision agent is unit-tested in test_app_chat_routes.py via
    _validate_attachments, since every ACTIVE_AGENT is now vision-capable.)"""
    img = "data:image/jpeg;base64,AAAA"
    client = app_state["client"]
    sid = _new_session(client, agent=agent)
    resp = _post_stream(client, {
        "agent": agent, "session_id": sid, "message": "what's this?",
        "attachments": [img],
    })
    assert resp.status_code == 200
    events = _parse_sse(resp.data)
    assert events[-1]["type"] == "done"
    captured = app_state["stream"].calls[-1]["request"]
    last_user = captured.messages[-1]
    assert isinstance(last_user.content, list)
    assert any(p.get("type") == "image_url" and p["image_url"]["url"] == img
               for p in last_user.content)


def test_chat_stream_rejects_non_list_attachments(app_state):
    client = app_state["client"]
    sid = _new_session(client, agent="aetheria")
    resp = _post_stream(client, {
        "agent": "aetheria", "session_id": sid, "message": "hi",
        "attachments": "not a list",
    })
    assert resp.status_code == 400
    assert json.loads(resp.data)["error"]["code"] == "invalid_attachments"
    assert app_state["stream"].calls == []


def test_chat_stream_rejects_non_string_entry(app_state):
    client = app_state["client"]
    sid = _new_session(client, agent="aetheria")
    resp = _post_stream(client, {
        "agent": "aetheria", "session_id": sid, "message": "hi",
        "attachments": [42],
    })
    assert resp.status_code == 400
    assert json.loads(resp.data)["error"]["code"] == "invalid_attachments"
    assert app_state["stream"].calls == []


def test_chat_stream_empty_attachments_list_treated_as_absent(app_state):
    """[] should behave like attachments missing — no error, no splice."""
    client = app_state["client"]
    sid = _new_session(client, agent="aetheria")
    resp = _post_stream(client, {
        "agent": "aetheria", "session_id": sid, "message": "hi",
        "attachments": [],
    })
    assert resp.status_code == 200
    events = _parse_sse(resp.data)
    assert events[-1]["type"] == "done"
    captured = app_state["stream"].calls[-1]["request"]
    last_user = captured.messages[-1]
    assert isinstance(last_user.content, str)  # no splice happened


def test_chat_stream_route_response_omits_raw(app_state):
    """Constraint 6: StreamChunk.raw stays internal; not in route response."""
    s = app_state["client"].post("/sessions",
                                 data=json.dumps({"agent": "aetheria"}),
                                 content_type="application/json")
    sid = json.loads(s.data)["session_id"]
    resp = _post_stream(app_state["client"],
                        {"agent": "aetheria", "session_id": sid, "message": "hi"})
    events = _parse_sse(resp.data)
    for e in events:
        assert "raw" not in e
