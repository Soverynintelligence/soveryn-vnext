"""Tests for soveryn/app/routes/compat.py — UI compat endpoints.

Uses Flask test_client; localhost guard bypassed via app.config.
Mirrors the pattern in tests/test_app_chat_routes.py.
"""

import json

from soveryn.config import runtime
from pathlib import Path

import pytest

from soveryn.agents.loop import AgentLoop
from soveryn.agents.personas import PERSONAS
from soveryn.app.startup import create_app
from soveryn.config.runtime import ACTIVE_AGENTS
from soveryn.inference.llama_server_client import ChatResponse
from soveryn.memory.conversation_store import ConversationStore


@pytest.fixture
def app_state(tmp_path, monkeypatch):
    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    conv = ConversationStore(tmp_path / "conv.db")
    fake_chat = lambda req, server, timeout=60: ChatResponse(
        content="ok", finish_reason="stop", tool_calls=None, usage=None, raw={})
    loops = {n: AgentLoop(n, conv, chat_fn=fake_chat) for n in ACTIVE_AGENTS}
    app = create_app(conv_store=conv, agent_loops=loops)
    app.config["SOVERYN_REQUIRE_LOCALHOST"] = False
    # Keep loops reachable for persona hot-reload assertions.
    app.extensions["soveryn"]["agent_loops"] = loops
    client = app.test_client()
    client._soveryn_loops = loops  # type: ignore[attr-defined]
    return client


def _err(resp):
    return json.loads(resp.data)["error"]


# ─── /api/models ─────────────────────────────────────────────────────────────

def test_api_models_returns_flat_map_of_active_agents(app_state):
    resp = app_state.get("/api/models")
    assert resp.status_code == 200
    payload = json.loads(resp.data)
    assert set(payload.keys()) == set(ACTIVE_AGENTS)
    # Values identify the backing model. Until 2026-08-02 every backend was
    # llama.cpp and every value was a .gguf basename; Vett + Scotty now run on
    # vLLM on the Spark, where there is no GGUF file. The contract is "a
    # non-empty identifier", not "a filename" — a fake .gguf name would have
    # kept this test green while lying about what is serving the agent.
    for agent, fname in payload.items():
        assert isinstance(fname, str) and fname, f"{agent} → {fname!r}"
        local = fname.endswith(".gguf")
        remote = any(
            s.model_alias and s.host != "127.0.0.1" and fname in str(s.model_path)
            for s in runtime.MODEL_SERVERS
        )
        assert local or remote, (
            f"{agent} → {fname!r} is neither a .gguf basename nor a remote "
            "backend identifier"
        )


def test_api_models_aetheria_has_a_gguf(app_state):
    payload = json.loads(app_state.get("/api/models").data)
    assert payload["aetheria"].endswith(".gguf")


def test_api_models_omits_folded_vett_and_scotty(app_state):
    payload = json.loads(app_state.get("/api/models").data)
    assert "vett" not in payload
    assert "scotty" not in payload
    assert set(payload) <= set(ACTIVE_AGENTS)


def test_api_models_excludes_retired_agents(app_state):
    payload = json.loads(app_state.get("/api/models").data)
    for retired in ("scout", "vision", "tinker", "forge", "aetheria_public"):
        assert retired not in payload


def test_api_models_no_stub_marker(app_state):
    """This is a REAL endpoint, not a stub — must not carry _stub flag."""
    payload = json.loads(app_state.get("/api/models").data)
    assert "_stub" not in payload


# ─── /api/persona/<agent> ────────────────────────────────────────────────────

def test_api_persona_aetheria_returns_canonical_persona(app_state):
    resp = app_state.get("/api/persona/aetheria")
    assert resp.status_code == 200
    payload = json.loads(resp.data)
    assert payload["agent"] == "aetheria"
    assert payload["persona"] == PERSONAS["aetheria"]
    assert payload["source"] == "baked"
    assert payload["baked"] == PERSONAS["aetheria"]


def test_api_persona_each_active_agent_round_trips(app_state):
    for name in ACTIVE_AGENTS:
        resp = app_state.get(f"/api/persona/{name}")
        assert resp.status_code == 200
        payload = json.loads(resp.data)
        assert payload["agent"] == name
        assert payload["persona"]
        if name == "kernel":
            assert payload["source"] in ("baked", "tower")
        else:
            assert payload["persona"] == PERSONAS[name]
            assert payload["source"] == "baked"


def test_api_persona_put_and_reset(app_state):
    agent = "eve"
    edited = "Eve test override — short and operational."
    resp = app_state.put(f"/api/persona/{agent}", json={"persona": edited})
    assert resp.status_code == 200
    payload = json.loads(resp.data)
    assert payload["ok"] is True
    assert payload["persona"] == edited
    assert payload["source"] == "override"
    assert app_state._soveryn_loops[agent].system_prompt == edited

    got = json.loads(app_state.get(f"/api/persona/{agent}").data)
    assert got["persona"] == edited
    assert got["source"] == "override"

    reset = app_state.delete(f"/api/persona/{agent}")
    assert reset.status_code == 200
    back = json.loads(reset.data)
    assert back["source"] == "baked"
    assert back["persona"] == PERSONAS[agent]
    assert app_state._soveryn_loops[agent].system_prompt == PERSONAS[agent]


def test_api_persona_put_rejects_empty(app_state):
    resp = app_state.put("/api/persona/eve", json={"persona": "   "})
    assert resp.status_code == 400
    assert _err(resp)["code"] == "bad_request"


@pytest.mark.parametrize("retired", [
    "scout", "vision", "tinker", "forge",
    "ares_llm", "aetheria_public", "telegram", "chromadb",
])
def test_api_persona_retired_agent_400(app_state, retired):
    resp = app_state.get(f"/api/persona/{retired}")
    assert resp.status_code == 400
    assert _err(resp)["code"] == "retired_agent"


def test_api_persona_unknown_agent_400(app_state):
    resp = app_state.get("/api/persona/fnord")
    assert resp.status_code == 400
    assert _err(resp)["code"] == "unknown_agent"


def test_api_persona_no_stub_marker(app_state):
    payload = json.loads(app_state.get("/api/persona/aetheria").data)
    assert "_stub" not in payload


# ─── /api/message_board ──────────────────────────────────────────────────────

def test_api_message_board_no_agent_returns_dict_for_all_active(app_state):
    resp = app_state.get("/api/message_board")
    assert resp.status_code == 200
    payload = json.loads(resp.data)
    assert payload["_stub"] is True
    for name in ACTIVE_AGENTS:
        assert payload[name] == []
    # No retired agents in the dict
    for retired in ("scout", "ares_llm", "vision"):
        assert retired not in payload


def test_api_message_board_specific_active_agent(app_state):
    resp = app_state.get("/api/message_board?agent=aetheria")
    assert resp.status_code == 200
    payload = json.loads(resp.data)
    assert payload["_stub"] is True
    assert payload["aetheria"] == []


@pytest.mark.parametrize("retired", ["scout", "vision", "tinker", "telegram", "chromadb"])
def test_api_message_board_retired_agent_400(app_state, retired):
    resp = app_state.get(f"/api/message_board?agent={retired}")
    assert resp.status_code == 400
    assert _err(resp)["code"] == "retired_agent"


def test_api_message_board_unknown_agent_400(app_state):
    resp = app_state.get("/api/message_board?agent=fnord")
    assert resp.status_code == 400
    assert _err(resp)["code"] == "unknown_agent"


# ─── POST /api/message_board/clear ───────────────────────────────────────────

def test_api_message_board_clear_stub_response(app_state):
    resp = app_state.post("/api/message_board/clear")
    assert resp.status_code == 200
    payload = json.loads(resp.data)
    assert payload["_stub"] is True
    assert payload["deleted"] == []
    assert "not implemented" in payload["message"].lower()


# ─── /api/research_journal ───────────────────────────────────────────────────

def test_api_research_journal_returns_empty_stub(app_state):
    resp = app_state.get("/api/research_journal")
    assert resp.status_code == 200
    payload = json.loads(resp.data)
    assert payload["_stub"] is True
    assert payload["content"] == ""


# ─── Deferred endpoints — verify they 404 with JSON envelope ─────────────────

def test_api_memory_evidence_returns_404(app_state):
    """Deferred entirely. UI should get the global JSON 404 envelope."""
    resp = app_state.get("/api/memory/evidence")
    assert resp.status_code == 404
    assert _err(resp)["code"] == "not_found"


# ─── TODO markers are grep-able and ticket-style ─────────────────────────────

def test_todo_markers_use_ticket_format(tmp_path):
    """Every TODO in routes/compat.py must be TODO(vnext-<slug>) for grep."""
    import re
    path = str(Path.home() / "soveryn_vnext" / "soveryn" / "app" / "routes" / "compat.py")
    with open(path) as f:
        content = f.read()
    plain_todos = re.findall(r"\bTODO\b(?!\()", content)
    assert plain_todos == [], (
        f"Found bare TODO without ticket slug: {plain_todos}. "
        "Use TODO(vnext-<area>) so they're grep-able."
    )


def test_stub_endpoints_carry_stub_marker(app_state):
    """Defense in depth: every stub endpoint's payload has _stub: true."""
    for path in ("/api/message_board", "/api/research_journal"):
        resp = app_state.get(path)
        assert resp.status_code == 200
        assert json.loads(resp.data).get("_stub") is True, f"{path} missing _stub marker"
