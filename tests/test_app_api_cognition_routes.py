"""Tests for GET /api/cognition/note and GET /api/cognition/reflections.

Behavior under test:
- GET /api/cognition/note → {"content": <str>, "id": <str|null>} (200).
- Empty store → note returns {"content": "", "id": null} (200, not 500).
- GET /api/cognition/reflections → list newest-first with scope/citations/
  jon_originated; ?limit=N truncates to N.
"""

from __future__ import annotations

import pytest

from soveryn.agents.cognition.store import CognitionStore
from soveryn.agents.cognition.types import CandidateObservation
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
    app.config["SOVERYN_START_MESSENGER_WORKER"] = False
    # Inject a real CognitionStore — same pattern as coord fixture.
    app.extensions["soveryn"]["cognition_store"] = CognitionStore(lattice_path)
    return app.test_client(), lattice_path


# ─── /api/cognition/note ─────────────────────────────────────────────────────


def test_note_returns_note_content_and_id(client):
    test_client, lattice_path = client
    store = CognitionStore(lattice_path)
    nv = store.write_note_version("Jon reads hedging as noise")
    resp = test_client.get("/api/cognition/note")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["content"] == "Jon reads hedging as noise"
    assert data["id"] == nv.id


def test_note_empty_store_returns_empty_not_500(client):
    test_client, _ = client
    resp = test_client.get("/api/cognition/note")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["content"] == ""
    assert data["id"] is None


# ─── /api/cognition/reflections ──────────────────────────────────────────────


def _seed_reflection(store: CognitionStore, text: str, scope: str = "manner") -> str:
    """Write one reflection and return its id."""
    obs = CandidateObservation(
        text=text,
        scope=scope,
        citations=("turn-1",),
        jon_originated=True,
    )
    return store.write_reflection(obs).id


def test_reflections_returns_newest_first_with_fields(client):
    test_client, lattice_path = client
    store = CognitionStore(lattice_path)
    _seed_reflection(store, "alpha", scope="manner")
    _seed_reflection(store, "beta", scope="value")
    _seed_reflection(store, "gamma", scope="unsure")

    resp = test_client.get("/api/cognition/reflections")
    assert resp.status_code == 200
    items = resp.get_json()
    assert isinstance(items, list)
    assert len(items) == 3
    # Newest-first: gamma was written last.
    assert items[0]["text"] == "gamma"
    assert items[-1]["text"] == "alpha"
    # Required fields present on every item.
    for item in items:
        assert "id" in item
        assert "text" in item
        assert "scope" in item
        assert "citations" in item
        assert "jon_originated" in item
        assert "created_at" in item
    # Specific values for gamma.
    assert items[0]["scope"] == "unsure"
    assert items[0]["citations"] == ["turn-1"]
    assert items[0]["jon_originated"] is True


def test_reflections_limit_param_truncates(client):
    test_client, lattice_path = client
    store = CognitionStore(lattice_path)
    for i in range(3):
        _seed_reflection(store, f"obs-{i}")

    resp = test_client.get("/api/cognition/reflections?limit=2")
    assert resp.status_code == 200
    items = resp.get_json()
    assert len(items) == 2


def test_reflections_empty_store_returns_empty_list(client):
    test_client, _ = client
    resp = test_client.get("/api/cognition/reflections")
    assert resp.status_code == 200
    assert resp.get_json() == []
