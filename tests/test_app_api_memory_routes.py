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


# ─── /api/memory/library_writes ─────────────────────────────────────────────

@pytest.fixture
def library_seeded_lattice(tmp_path):
    """Seed a lattice with a mix of library + library_chunk + non-library
    nodes so the route's type-filter is exercised."""
    store = LatticeStore(tmp_path / "lattice.db")
    base = datetime.now(timezone.utc)
    import uuid, json
    with store._conn() as conn:
        rows = [
            # (offset_min, agent, node_type, content, tags)
            (0, "aetheria", "library", "Newest aetheria synthesis", ["synthesis"]),
            (5, "scotty", "library", "DAC milestone note", ["milestone", "dac"]),
            (10, "aetheria", "library_chunk", "doc fragment (should NOT appear)", []),
            (15, "vett", "library", "Funding research summary", ["research"]),
            (60, "aetheria", "fact", "private fact (NOT library layer)", []),
        ]
        for offset_min, agent, node_type, content, tags in rows:
            ts = (base - timedelta(minutes=offset_min)).isoformat()
            node_id = f"n-{uuid.uuid4().hex[:8]}"
            layer = "library" if node_type in ("library", "library_chunk") else "private"
            conn.execute(
                "INSERT INTO nodes (id, type, layer, agent, content, intensity, "
                "salience, access_count, tags, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 0.3, 0.5, 0, ?, ?, ?)",
                (node_id, node_type, layer, agent, content,
                 json.dumps(tags), ts, ts),
            )
    return tmp_path / "lattice.db"


@pytest.fixture
def library_client(tmp_path, fake_chat, library_seeded_lattice, monkeypatch):
    monkeypatch.setenv("SOVERYN_LATTICE_DB", str(library_seeded_lattice))
    conv = ConversationStore(tmp_path / "conv.db")
    loops = {n: AgentLoop(n, conv, chat_fn=fake_chat) for n in ACTIVE_AGENTS}
    app = create_app(conv_store=conv, agent_loops=loops)
    app.config["SOVERYN_REQUIRE_LOCALHOST"] = False
    return app.test_client()


def test_library_writes_default_returns_newest_first(library_client):
    resp = library_client.get("/api/memory/library_writes")
    assert resp.status_code == 200
    data = resp.get_json()
    # 3 library nodes, no library_chunk, no fact
    assert len(data["writes"]) == 3
    heads = [w["content_head"] for w in data["writes"]]
    assert "doc fragment (should NOT appear)" not in heads
    assert "private fact (NOT library layer)" not in heads
    # Order: newest first by created_at
    assert data["writes"][0]["content_head"] == "Newest aetheria synthesis"
    assert data["writes"][1]["agent"] == "scotty"
    assert data["writes"][2]["agent"] == "vett"


def test_library_writes_respects_limit(library_client):
    resp = library_client.get("/api/memory/library_writes?limit=2")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["limit"] == 2
    assert len(data["writes"]) == 2


def test_library_writes_clamps_max_limit(library_client):
    resp = library_client.get("/api/memory/library_writes?limit=999")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["limit"] == 50  # max


def test_library_writes_rejects_non_int(library_client):
    resp = library_client.get("/api/memory/library_writes?limit=banana")
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "invalid_message"


def test_library_writes_rejects_zero_and_negative(library_client):
    resp = library_client.get("/api/memory/library_writes?limit=0")
    assert resp.status_code == 400
    resp = library_client.get("/api/memory/library_writes?limit=-1")
    assert resp.status_code == 400


def test_library_writes_includes_tags_and_id(library_client):
    resp = library_client.get("/api/memory/library_writes")
    data = resp.get_json()
    scotty_write = next(w for w in data["writes"] if w["agent"] == "scotty")
    assert set(scotty_write["tags"]) == {"milestone", "dac"}
    assert scotty_write["id"]
    assert scotty_write["created_at"]


def test_library_writes_agent_filter_restricts_results(library_client):
    resp = library_client.get("/api/memory/library_writes?agent=scotty")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["agent_filter"] == "scotty"
    agents = {w["agent"] for w in data["writes"]}
    assert agents == {"scotty"}


def test_library_writes_tag_contains_filter(library_client):
    resp = library_client.get("/api/memory/library_writes?tag_contains=milestone")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["tag_contains"] == "milestone"
    # Only the scotty write (tagged with 'milestone') matches
    assert len(data["writes"]) == 1
    assert data["writes"][0]["agent"] == "scotty"


def test_library_writes_combined_filters(library_client):
    resp = library_client.get(
        "/api/memory/library_writes?agent=scotty&tag_contains=dac"
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["agent_filter"] == "scotty"
    assert data["tag_contains"] == "dac"
    assert all(w["agent"] == "scotty" for w in data["writes"])


def test_library_writes_empty_filter_strings_treated_as_no_filter(library_client):
    """`?agent=&tag_contains=` should behave like no filter (full results)."""
    resp = library_client.get("/api/memory/library_writes?agent=&tag_contains=")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["agent_filter"] is None
    assert data["tag_contains"] is None
    assert len(data["writes"]) == 3  # all library-type writes
