"""Tests for /api/specialists/* mission-control endpoints + the DAC
edges route under api_memory."""

from __future__ import annotations

import json
import sqlite3

import pytest

from soveryn.agents.loop import AgentLoop
from soveryn.app.startup import create_app
from soveryn.config.runtime import ACTIVE_AGENTS
from soveryn.inference.llama_server_client import ChatResponse
from soveryn.memory.conversation_store import ConversationStore


@pytest.fixture
def fake_chat():
    return lambda req, server, timeout=60: ChatResponse(
        content="ok", finish_reason="stop", tool_calls=None, usage=None, raw={})


@pytest.fixture
def seeded_conv_lattice(tmp_path):
    """Seed conv_meta + lattice with specialists and DAC traffic."""
    conv = tmp_path / "conv.db"
    lattice = tmp_path / "lattice.db"
    # conv_meta from real ConversationStore so the schema matches production
    store = ConversationStore(conv)
    # Direct SQL inserts because new_session() generates fresh uuids
    with sqlite3.connect(str(conv)) as con:
        rows = [
            ("a-active", "vett", "[specialist:detector:n1]", "2026-06-07T18:00:00"),
            ("b-active", "scotty", "[specialist:bench:n2]", "2026-06-07T19:30:00"),
            ("c-archived", "vett", "[specialist-archived:done:n3]", "2026-06-07T15:00:00"),
            ("d-killed", "scotty", "[specialist-killed:zap:n4]", "2026-06-07T16:00:00"),
            ("e-direct", "vett", "[direct:n5]", "2026-06-07T17:00:00"),
        ]
        for sid, agent, title, created in rows:
            con.execute(
                "INSERT INTO conversation_meta (session_id, agent, title, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (sid, agent, title, created, created),
            )
    # Lattice with one DAC edge
    from soveryn.memory.lattice import LatticeStore
    lstore = LatticeStore(lattice)
    with sqlite3.connect(str(lattice)) as con:
        prov = json.dumps({
            "kind": "direct_message", "sender": "aetheria",
            "target": "scotty", "session_id": "ss", "mode": "execute",
            "coord_node_id": "coord-1",
        })
        con.execute(
            "INSERT INTO nodes (id, type, layer, agent, content, intensity, "
            "salience, access_count, tags, created_at, updated_at, provenance) "
            "VALUES ('coord-1', 'coordination', 'lattice', 'aetheria', "
            "'coord', 0.3, 0.5, 0, '[]', ?, ?, NULL)",
            ("2026-06-07T18:00:00", "2026-06-07T18:00:00"),
        )
        con.execute(
            "INSERT INTO nodes (id, type, layer, agent, content, intensity, "
            "salience, access_count, tags, created_at, updated_at, provenance) "
            "VALUES ('msg-1', 'direct_message', 'private', 'aetheria', ?, "
            "0.3, 0.5, 0, '[]', ?, ?, ?)",
            (
                "[direct_execute] aetheria -> scotty\n"
                "session: ss\ncoord: coord-1\n"
                "head: Implement the detector now",
                "2026-06-07T18:30:00", "2026-06-07T18:30:00",
                prov,
            ),
        )
        con.execute(
            "INSERT INTO edges (id, source_id, target_id, relationship, "
            "strength, bidirectional, archived, reinforcement_count, "
            "reinforced_at, created_at) VALUES "
            "('edge-1', 'msg-1', 'coord-1', 'direct_command', 0.5, 0, 0, 1, "
            "?, ?)",
            ("2026-06-07T18:30:00", "2026-06-07T18:30:00"),
        )
    return conv, lattice


@pytest.fixture
def client(tmp_path, fake_chat, seeded_conv_lattice, monkeypatch):
    conv_path, lattice_path = seeded_conv_lattice
    monkeypatch.setenv("SOVERYN_LATTICE_DB", str(lattice_path))
    monkeypatch.setenv("SOVERYN_CONVERSATIONS_DB", str(conv_path))
    # Isolate data_root too. Without it the comm-bus route reads the REAL
    # data/delegation.db and the test asserts against production (2026-07-30).
    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    conv = ConversationStore(conv_path)
    loops = {n: AgentLoop(n, conv, chat_fn=fake_chat) for n in ACTIVE_AGENTS}
    app = create_app(conv_store=conv, agent_loops=loops)
    app.config["SOVERYN_REQUIRE_LOCALHOST"] = False
    return app.test_client()


# ─── /api/specialists/active ─────────────────────────────────────────────────


def test_active_returns_only_active_specialists(client):
    resp = client.get("/api/specialists/active")
    assert resp.status_code == 200
    data = resp.get_json()
    sids = {s["specialist_id"] for s in data["active"]}
    assert sids == {"a-active", "b-active"}
    assert data["count"] == 2


def test_active_returns_newest_first(client):
    resp = client.get("/api/specialists/active")
    data = resp.get_json()
    assert data["active"][0]["specialist_id"] == "b-active"
    assert data["active"][1]["specialist_id"] == "a-active"


def test_active_carries_parsed_name_and_coord(client):
    resp = client.get("/api/specialists/active")
    data = resp.get_json()
    by_sid = {s["specialist_id"]: s for s in data["active"]}
    assert by_sid["a-active"]["name"] == "detector"
    assert by_sid["a-active"]["coord_node_id"] == "n1"
    assert by_sid["a-active"]["host_agent"] == "vett"


# ─── /api/specialists/kill ──────────────────────────────────────────────────


def test_kill_retitles_active_specialist(client):
    resp = client.post(
        "/api/specialists/kill",
        data=json.dumps({"specialist_id": "a-active"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["killed_title"] == "[specialist-killed:detector:n1]"
    # Now active list should not contain it
    listing = client.get("/api/specialists/active").get_json()
    sids = {s["specialist_id"] for s in listing["active"]}
    assert "a-active" not in sids


def test_kill_rejects_missing_specialist_id(client):
    resp = client.post(
        "/api/specialists/kill",
        data=json.dumps({}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "missing_field"


def test_kill_returns_404_on_unknown(client):
    resp = client.post(
        "/api/specialists/kill",
        data=json.dumps({"specialist_id": "ghost"}),
        content_type="application/json",
    )
    assert resp.status_code == 404
    assert resp.get_json()["error"]["code"] == "unknown_specialist"


def test_kill_returns_409_on_non_active_session(client):
    resp = client.post(
        "/api/specialists/kill",
        data=json.dumps({"specialist_id": "c-archived"}),
        content_type="application/json",
    )
    assert resp.status_code == 409
    assert resp.get_json()["error"]["code"] == "not_active_specialist"


def test_kill_rejects_non_json_body(client):
    resp = client.post("/api/specialists/kill", data="not json",
                       content_type="text/plain")
    assert resp.status_code == 400


# ─── /api/memory/dac_edges ──────────────────────────────────────────────────


def test_dac_edges_returns_seeded_edge(client):
    resp = client.get("/api/memory/dac_edges")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["edges"]) == 1
    e = data["edges"][0]
    assert e["relationship"] == "direct_command"
    assert e["sender"] == "aetheria"
    assert e["target"] == "scotty"
    assert e["coord_node_id"] == "coord-1"
    assert "detector now" in e["message_head"]


def test_dac_edges_respects_limit_param(client):
    resp = client.get("/api/memory/dac_edges?limit=5")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["limit"] == 5


def test_dac_edges_rejects_non_int(client):
    resp = client.get("/api/memory/dac_edges?limit=banana")
    assert resp.status_code == 400


def test_dac_edges_rejects_zero_or_negative(client):
    assert client.get("/api/memory/dac_edges?limit=0").status_code == 400
    assert client.get("/api/memory/dac_edges?limit=-1").status_code == 400
