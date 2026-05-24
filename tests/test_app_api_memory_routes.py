"""Tests for /api/memory/activity route."""

from datetime import datetime, timezone, timedelta
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
def seeded_lattice(tmp_path):
    store = LatticeStore(tmp_path / "lattice.db")
    base = datetime.now(timezone.utc)
    with store._conn() as conn:
        for offset, agent in [(0, "aetheria"), (0, "vett"), (1, "aetheria")]:
            ts = (base - timedelta(days=offset)).isoformat()
            # Unique suffix to avoid PRIMARY KEY collision when (offset, agent) repeats
            import uuid
            node_id = f"n-{offset}-{agent}-{uuid.uuid4().hex[:8]}"
            conn.execute(
                "INSERT INTO nodes (id, type, layer, agent, content, intensity, salience, access_count, tags, created_at, updated_at)"
                " VALUES (?, 'fact', 'private', ?, 'x', 0.3, 0.5, 0, '[]', ?, ?)",
                (node_id, agent, ts, ts),
            )
    return tmp_path / "lattice.db"


@pytest.fixture
def client(tmp_path, fake_chat, seeded_lattice, monkeypatch):
    monkeypatch.setenv("SOVERYN_LATTICE_DB", str(seeded_lattice))
    conv = ConversationStore(tmp_path / "conv.db")
    loops = {n: AgentLoop(n, conv, chat_fn=fake_chat) for n in ACTIVE_AGENTS}
    app = create_app(conv_store=conv, agent_loops=loops)
    app.config["SOVERYN_REQUIRE_LOCALHOST"] = False
    return app.test_client()


def test_memory_activity_default_days(client):
    resp = client.get("/api/memory/activity")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "buckets" in data
    assert len(data["buckets"]) == 14  # default


def test_memory_activity_days_param(client):
    resp = client.get("/api/memory/activity?days=7")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["buckets"]) == 7


def test_memory_activity_clamps_max(client):
    resp = client.get("/api/memory/activity?days=999")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["buckets"]) <= 90  # capped at 90


def test_memory_activity_rejects_non_int(client):
    resp = client.get("/api/memory/activity?days=banana")
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"]["code"] == "invalid_message"


def test_memory_activity_rejects_negative(client):
    resp = client.get("/api/memory/activity?days=-3")
    assert resp.status_code == 400


def test_memory_activity_includes_per_agent(client):
    resp = client.get("/api/memory/activity?days=2")
    data = resp.get_json()
    flat = {b["date"]: b for b in data["buckets"]}
    today = max(flat)  # latest day in window
    assert flat[today]["count"] >= 1
