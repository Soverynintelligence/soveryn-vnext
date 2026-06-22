"""Tests for the POST /api/coord create endpoint — Mission Control's human
board-create surface (lets Jon open a board item himself; agent-driven create
already exists via tool dispatch).

Behavior under test:
- POST /api/coord creates an Open coordination node and returns it (201).
- Default notifies the team (emits NODE_CREATED → webhook routing).
- notify=false parks the item quietly (no event → no agent triggered).
- Unknown board / empty content → 400.
"""

from __future__ import annotations

import sqlite3

import pytest

from soveryn.agents.loop import AgentLoop
from soveryn.app.startup import create_app
from soveryn.config.runtime import ACTIVE_AGENTS
from soveryn.inference.llama_server_client import ChatResponse
from soveryn.memory.conversation_store import ConversationStore
from soveryn.memory.lattice import LatticeStore


@pytest.fixture
def fake_chat():
    return lambda req, server, timeout=60: ChatResponse(
        content="ok", finish_reason="stop", tool_calls=None, usage=None, raw={})


@pytest.fixture
def env_paths(tmp_path, monkeypatch):
    conv_path = tmp_path / "conv.db"
    lattice_path = tmp_path / "lattice.db"
    LatticeStore(lattice_path)  # init full schema (idempotent)
    monkeypatch.setenv("SOVERYN_LATTICE_DB", str(lattice_path))
    monkeypatch.setenv("SOVERYN_CONVERSATIONS_DB", str(conv_path))
    return conv_path, lattice_path


@pytest.fixture
def client(env_paths, fake_chat):
    conv_path, lattice_path = env_paths
    conv = ConversationStore(conv_path)
    loops = {n: AgentLoop(n, conv, chat_fn=fake_chat) for n in ACTIVE_AGENTS}
    app = create_app(conv_store=conv, agent_loops=loops)
    # create_app only auto-wires coord_store on the path where it builds its
    # own agent_loops (the `agent_loops is None` branch). We inject loops for
    # test isolation, so wire a real CoordinationStore over the same lattice
    # ourselves — same store class the route uses in production. No event
    # worker is started, so emitted events just land in coord_event_log
    # (which is exactly what we assert on); no agent is actually invoked.
    from soveryn.platform.coordination import CoordinationStore
    from soveryn.platform.coordination.events import InMemoryEventBus
    app.extensions["soveryn"]["coord_store"] = CoordinationStore(
        lattice_path, event_bus=InMemoryEventBus())
    return app.test_client()


def _events_for(lattice_path, node_id):
    with sqlite3.connect(str(lattice_path)) as conn:
        return conn.execute(
            "SELECT kind FROM coord_event_log WHERE node_id = ?", (node_id,)
        ).fetchall()


def test_create_endpoint_creates_open_node(client):
    resp = client.post("/api/coord", json={"board": "Signal", "content": "note to the team"})
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["board"] == "Signal"
    assert data["status"] == "Open"
    assert len(data["id"]) == 36
    assert data["owner"] == "jon"  # human default


def test_create_endpoint_default_notifies(client, env_paths):
    _, lattice_path = env_paths
    resp = client.post("/api/coord", json={"board": "Signal", "content": "x"})
    node_id = resp.get_json()["id"]
    assert ("node_created",) in _events_for(lattice_path, node_id)


def test_create_endpoint_notify_false_parks_quietly(client, env_paths):
    _, lattice_path = env_paths
    resp = client.post(
        "/api/coord",
        json={"board": "Blueprint", "content": "park until hardware", "notify": False},
    )
    assert resp.status_code == 201
    node_id = resp.get_json()["id"]
    assert _events_for(lattice_path, node_id) == []  # nobody triggered


def test_create_endpoint_rejects_unknown_board(client):
    resp = client.post("/api/coord", json={"board": "Nope", "content": "x"})
    assert resp.status_code == 400


def test_create_endpoint_rejects_empty_content(client):
    resp = client.post("/api/coord", json={"board": "Signal", "content": "   "})
    assert resp.status_code == 400
