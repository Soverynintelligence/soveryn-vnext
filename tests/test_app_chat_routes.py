"""Tests for soveryn.app — Flask app surface.

Uses app.test_client() — no real network. AgentLoop's chat_fn is injected
as a fake so no urllib calls are made. tmp_path SQLite for conv_store.
"""

import json
import pytest

from soveryn.agents.loop import AgentLoop
from soveryn.app.startup import create_app
from soveryn.config.runtime import ACTIVE_AGENTS
from soveryn.inference.llama_server_client import (
    ChatResponse,
    LlamaServerError,
    LlamaServerTimeout,
)
from soveryn.memory.conversation_store import ConversationStore


# ─── Test infrastructure ─────────────────────────────────────────────────────

class _FakeChat:
    def __init__(self, *, content="hello back", finish_reason="stop", raise_exc=None):
        self.calls: list[dict] = []
        self.content = content
        self.finish_reason = finish_reason
        self.raise_exc = raise_exc

    def __call__(self, request, server, timeout=60.0):
        self.calls.append({"request": request, "server": server})
        if self.raise_exc is not None:
            raise self.raise_exc
        return ChatResponse(
            content=self.content,
            finish_reason=self.finish_reason,
            tool_calls=None,
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            raw={},
        )


@pytest.fixture
def fake_chat():
    return _FakeChat()


@pytest.fixture
def app_state(tmp_path, fake_chat):
    """Build a fully wired Flask app with localhost-guard disabled for testing."""
    conv = ConversationStore(tmp_path / "app_conv.db")
    loops = {name: AgentLoop(name, conv, chat_fn=fake_chat) for name in ACTIVE_AGENTS}
    app = create_app(conv_store=conv, agent_loops=loops)
    app.config["SOVERYN_REQUIRE_LOCALHOST"] = False  # bypass via app.config only
    return {"app": app, "client": app.test_client(), "conv": conv, "fake_chat": fake_chat}


def _err(resp):
    return json.loads(resp.data)["error"]


def _post(client, path, body, content_type="application/json"):
    return client.post(path, data=json.dumps(body), content_type=content_type)


# ─── /health ─────────────────────────────────────────────────────────────────

def test_health_returns_app_metadata(app_state):
    resp = app_state["client"].get("/health")
    assert resp.status_code == 200
    payload = json.loads(resp.data)
    assert payload["app"] == "soveryn"
    assert "version" in payload
    assert set(payload["active_agents"]) == set(ACTIVE_AGENTS)
    assert "preflight" not in payload  # default: skipped


def test_health_with_preflight_includes_summary(app_state, monkeypatch):
    from soveryn.app import preflight as pf
    # Inject a fake report so we don't probe the network.
    from soveryn.app.preflight import PreflightReport
    from soveryn.config.loader import load_env_config
    from soveryn.inference.health import HealthResult

    fake = PreflightReport(
        env=load_env_config(),
        results=(
            HealthResult("aetheria_primary", "model_server", "ok", 1.0, "fine"),
            HealthResult("vett_scotty_shared", "model_server", "fail", 0.5, "down"),
            HealthResult("heartbeat", "runtime_service", "deferred", 0.0, "thread"),
        ),
    )
    monkeypatch.setattr(pf, "run_preflight", lambda env=None, timeout=None: fake)

    resp = app_state["client"].get("/health?preflight=1")
    assert resp.status_code == 200
    payload = json.loads(resp.data)
    assert payload["preflight"]["ok"] is False
    assert payload["preflight"]["n_ok"] == 1
    assert payload["preflight"]["n_fail"] == 1
    assert payload["preflight"]["n_deferred"] == 1
    assert payload["preflight"]["failures"] == [
        {"name": "vett_scotty_shared", "kind": "model_server", "detail": "down"},
    ]


# ─── Localhost guard ─────────────────────────────────────────────────────────

def test_localhost_guard_default_on(tmp_path, fake_chat):
    """A fresh app must reject non-127.0.0.1 requests by default."""
    conv = ConversationStore(tmp_path / "g.db")
    loops = {name: AgentLoop(name, conv, chat_fn=fake_chat) for name in ACTIVE_AGENTS}
    app = create_app(conv_store=conv, agent_loops=loops)
    # Default config: REQUIRE_LOCALHOST is True.
    assert app.config["SOVERYN_REQUIRE_LOCALHOST"] is True
    client = app.test_client()
    resp = client.get("/health", environ_base={"REMOTE_ADDR": "10.0.0.5"})
    assert resp.status_code == 403
    assert _err(resp)["code"] == "localhost_required"


def test_localhost_guard_allows_127_0_0_1(tmp_path, fake_chat):
    conv = ConversationStore(tmp_path / "g2.db")
    loops = {name: AgentLoop(name, conv, chat_fn=fake_chat) for name in ACTIVE_AGENTS}
    app = create_app(conv_store=conv, agent_loops=loops)
    client = app.test_client()
    resp = client.get("/health", environ_base={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200


def test_localhost_guard_bypass_via_app_config(app_state):
    """app_state fixture bypassed the guard via app.config (already set False)."""
    resp = app_state["client"].get("/health", environ_base={"REMOTE_ADDR": "203.0.113.7"})
    assert resp.status_code == 200


# ─── /sessions CRUD ──────────────────────────────────────────────────────────

def test_create_session_requires_agent(app_state):
    resp = _post(app_state["client"], "/sessions", {})
    assert resp.status_code == 400
    assert _err(resp)["code"] == "missing_field"


def test_create_session_returns_201_and_session_id(app_state):
    resp = _post(app_state["client"], "/sessions", {"agent": "aetheria", "title": "hello"})
    assert resp.status_code == 201
    payload = json.loads(resp.data)
    assert payload["agent"] == "aetheria"
    assert payload["title"] == "hello"
    assert isinstance(payload["session_id"], str)
    assert len(payload["session_id"]) == 36


def test_create_session_rejects_retired_agent(app_state):
    resp = _post(app_state["client"], "/sessions", {"agent": "scout"})
    assert resp.status_code == 400
    assert _err(resp)["code"] == "retired_agent"


def test_create_session_rejects_unknown_agent(app_state):
    resp = _post(app_state["client"], "/sessions", {"agent": "fnord"})
    assert resp.status_code == 400
    assert _err(resp)["code"] == "unknown_agent"


def test_create_session_rejects_invalid_json_body(app_state):
    resp = app_state["client"].post(
        "/sessions", data="not json", content_type="application/json")
    assert resp.status_code == 400
    assert _err(resp)["code"] == "invalid_json"


def test_create_session_rejects_wrong_content_type(app_state):
    resp = app_state["client"].post(
        "/sessions", data=json.dumps({"agent": "aetheria"}), content_type="text/plain")
    assert resp.status_code == 400
    assert _err(resp)["code"] == "invalid_json"


def test_list_sessions_returns_empty_initially(app_state):
    resp = app_state["client"].get("/sessions")
    assert resp.status_code == 200
    assert json.loads(resp.data)["sessions"] == []


def test_list_sessions_filtered_by_agent(app_state):
    _post(app_state["client"], "/sessions", {"agent": "aetheria"})
    _post(app_state["client"], "/sessions", {"agent": "vett"})
    resp = app_state["client"].get("/sessions?agent=aetheria")
    sessions = json.loads(resp.data)["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["agent"] == "aetheria"


def test_get_history_404_for_missing_session(app_state):
    resp = app_state["client"].get("/sessions/does-not-exist/history")
    assert resp.status_code == 404
    assert _err(resp)["code"] == "missing_session"


def test_get_history_returns_turns_in_order(app_state):
    create = _post(app_state["client"], "/sessions", {"agent": "aetheria"})
    sid = json.loads(create.data)["session_id"]
    # Use /chat to seed turns
    _post(app_state["client"], "/chat",
          {"agent": "aetheria", "session_id": sid, "message": "hi"})
    resp = app_state["client"].get(f"/sessions/{sid}/history")
    payload = json.loads(resp.data)
    assert payload["session_id"] == sid
    assert payload["agent"] == "aetheria"
    assert [t["role"] for t in payload["turns"]] == ["user", "assistant"]
    assert payload["turns"][0]["content"] == "hi"


def test_delete_session_404_when_missing(app_state):
    resp = app_state["client"].delete("/sessions/nope")
    assert resp.status_code == 404
    assert _err(resp)["code"] == "missing_session"


def test_delete_session_removes_it(app_state):
    create = _post(app_state["client"], "/sessions", {"agent": "aetheria"})
    sid = json.loads(create.data)["session_id"]
    resp = app_state["client"].delete(f"/sessions/{sid}")
    assert resp.status_code == 200
    assert json.loads(resp.data) == {"deleted": sid}
    # Now gone:
    follow = app_state["client"].get(f"/sessions/{sid}/history")
    assert follow.status_code == 404


# ─── /chat ───────────────────────────────────────────────────────────────────

def test_chat_happy_path_returns_full_envelope(app_state):
    create = _post(app_state["client"], "/sessions", {"agent": "aetheria"})
    sid = json.loads(create.data)["session_id"]
    resp = _post(app_state["client"], "/chat",
                 {"agent": "aetheria", "session_id": sid, "message": "hello"})
    assert resp.status_code == 200
    payload = json.loads(resp.data)
    assert payload["agent"] == "aetheria"
    assert payload["session_id"] == sid
    assert payload["content"] == "hello back"
    assert payload["finish_reason"] == "stop"
    assert payload["tool_calls"] is None
    assert payload["usage"]["total_tokens"] == 2


def test_chat_rejects_empty_message(app_state):
    create = _post(app_state["client"], "/sessions", {"agent": "aetheria"})
    sid = json.loads(create.data)["session_id"]
    for bad in ["", "   ", "\n\t"]:
        resp = _post(app_state["client"], "/chat",
                     {"agent": "aetheria", "session_id": sid, "message": bad})
        assert resp.status_code == 400
        assert _err(resp)["code"] == "invalid_message"


def test_chat_rejects_non_string_message(app_state):
    create = _post(app_state["client"], "/sessions", {"agent": "aetheria"})
    sid = json.loads(create.data)["session_id"]
    for bad in [None, 42, ["a"], {"x": 1}]:
        resp = _post(app_state["client"], "/chat",
                     {"agent": "aetheria", "session_id": sid, "message": bad})
        assert resp.status_code == 400
        assert _err(resp)["code"] == "invalid_message"


def test_chat_rejects_missing_session_id(app_state):
    resp = _post(app_state["client"], "/chat",
                 {"agent": "aetheria", "message": "hi"})
    assert resp.status_code == 400
    assert _err(resp)["code"] == "missing_field"


def test_chat_404_when_session_does_not_exist(app_state):
    resp = _post(app_state["client"], "/chat",
                 {"agent": "aetheria", "session_id": "ghost", "message": "hi"})
    assert resp.status_code == 404
    assert _err(resp)["code"] == "missing_session"


def test_chat_409_when_session_belongs_to_other_agent(app_state):
    create = _post(app_state["client"], "/sessions", {"agent": "vett"})
    sid = json.loads(create.data)["session_id"]
    resp = _post(app_state["client"], "/chat",
                 {"agent": "aetheria", "session_id": sid, "message": "hi"})
    assert resp.status_code == 409
    assert _err(resp)["code"] == "session_agent_mismatch"


@pytest.mark.parametrize("retired", [
    "scout", "vision", "tinker", "forge",
    "ares_llm", "aetheria_public", "telegram", "chromadb",
])
def test_chat_rejects_retired_agents(app_state, retired):
    resp = _post(app_state["client"], "/chat",
                 {"agent": retired, "session_id": "x", "message": "hi"})
    assert resp.status_code == 400
    assert _err(resp)["code"] == "retired_agent"


def test_chat_502_on_llama_server_error(tmp_path):
    conv = ConversationStore(tmp_path / "e.db")
    fake = _FakeChat(raise_exc=LlamaServerError(500, "boom", "vett_scotty_shared"))
    loops = {name: AgentLoop(name, conv, chat_fn=fake) for name in ACTIVE_AGENTS}
    app = create_app(conv_store=conv, agent_loops=loops)
    app.config["SOVERYN_REQUIRE_LOCALHOST"] = False
    client = app.test_client()
    create = _post(client, "/sessions", {"agent": "aetheria"})
    sid = json.loads(create.data)["session_id"]
    resp = _post(client, "/chat",
                 {"agent": "aetheria", "session_id": sid, "message": "hi"})
    assert resp.status_code == 502
    assert _err(resp)["code"] == "chat_server_error"


def test_chat_504_on_llama_server_timeout(tmp_path):
    conv = ConversationStore(tmp_path / "t.db")
    fake = _FakeChat(raise_exc=LlamaServerTimeout("vett_scotty_shared", 60.0))
    loops = {name: AgentLoop(name, conv, chat_fn=fake) for name in ACTIVE_AGENTS}
    app = create_app(conv_store=conv, agent_loops=loops)
    app.config["SOVERYN_REQUIRE_LOCALHOST"] = False
    client = app.test_client()
    create = _post(client, "/sessions", {"agent": "aetheria"})
    sid = json.loads(create.data)["session_id"]
    resp = _post(client, "/chat",
                 {"agent": "aetheria", "session_id": sid, "message": "hi"})
    assert resp.status_code == 504
    assert _err(resp)["code"] == "chat_timeout"


def test_chat_response_includes_tool_calls_passthrough(tmp_path):
    """Raw tool_calls preserved from ChatResponse -> route response, untouched."""
    conv = ConversationStore(tmp_path / "tc.db")
    fake = _FakeChat()
    # Override the fake to return tool_calls:
    def call_with_tools(request, server, timeout=60.0):
        fake.calls.append({"request": request, "server": server})
        return ChatResponse(
            content="",
            finish_reason="tool_calls",
            tool_calls=({"id": "x", "function": {"name": "foo", "arguments": "{}"}},),
            usage=None,
            raw={},
        )
    loops = {name: AgentLoop(name, conv, chat_fn=call_with_tools) for name in ACTIVE_AGENTS}
    app = create_app(conv_store=conv, agent_loops=loops)
    app.config["SOVERYN_REQUIRE_LOCALHOST"] = False
    client = app.test_client()
    create = _post(client, "/sessions", {"agent": "aetheria"})
    sid = json.loads(create.data)["session_id"]
    resp = _post(client, "/chat",
                 {"agent": "aetheria", "session_id": sid, "message": "hi"})
    payload = json.loads(resp.data)
    assert payload["tool_calls"] == [{"id": "x", "function": {"name": "foo", "arguments": "{}"}}]
    assert payload["finish_reason"] == "tool_calls"


# ─── Unknown route / wrong method ────────────────────────────────────────────

def test_unknown_route_returns_404_envelope(app_state):
    resp = app_state["client"].get("/nope")
    assert resp.status_code == 404
    assert _err(resp)["code"] == "not_found"


def test_wrong_method_returns_405_envelope(app_state):
    # GET /chat now serves the chat UI HTML; use a still-POST-only sibling
    # (/chat_stream) to exercise the 405 envelope.
    resp = app_state["client"].get("/chat_stream")
    assert resp.status_code == 405
    assert _err(resp)["code"] == "method_not_allowed"


# ─── Factory does not bind / does not run ────────────────────────────────────

def test_create_app_does_not_call_run(tmp_path, fake_chat, monkeypatch):
    """The factory must NEVER call app.run() — that's the launcher's job."""
    conv = ConversationStore(tmp_path / "r.db")
    loops = {name: AgentLoop(name, conv, chat_fn=fake_chat) for name in ACTIVE_AGENTS}
    app = create_app(conv_store=conv, agent_loops=loops)
    # If create_app had called run(), the test would have hung or errored.
    # Sanity: the app object exists but no port is bound.
    assert app is not None
    # extensions dict has soveryn state
    assert set(app.extensions["soveryn"]["agent_loops"].keys()) == set(ACTIVE_AGENTS)
