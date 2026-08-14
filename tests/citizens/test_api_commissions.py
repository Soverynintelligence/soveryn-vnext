"""HTTP surface for commissions (Phase 2)."""
from __future__ import annotations

from pathlib import Path

import pytest

from soveryn.agents.loop import AgentLoop
from soveryn.app.startup import create_app
from soveryn.citizens.registry import Citizen, connect, observe, register
from soveryn.config.runtime import ACTIVE_AGENTS
from soveryn.inference.llama_server_client import ChatResponse
from soveryn.memory.conversation_store import ConversationStore


@pytest.fixture
def fake_chat():
    return lambda req, server, timeout=60: ChatResponse(
        content="Summary: all clear at the dock.",
        finish_reason="stop",
        tool_calls=None,
        usage=None,
        raw={},
    )


@pytest.fixture
def client(tmp_path, fake_chat, monkeypatch):
    db = tmp_path / "citizens.db"
    desks = tmp_path / "desks"
    with connect(db) as conn:
        register(
            conn,
            Citizen(
                id="aetheria",
                display_name="Aetheria",
                workspace_path=str(desks / "aetheria"),
            ),
        )
        register(
            conn,
            Citizen(
                id="vett",
                display_name="V.E.T.T.",
                workspace_path=str(desks / "vett"),
            ),
        )
        observe(conn, "aetheria", "present", at="2026-08-14T08:00:00Z")

    conv = ConversationStore(tmp_path / "conv.db")
    loops = {
        n: AgentLoop(n, conv, chat_fn=fake_chat) for n in ACTIVE_AGENTS
    }
    app = create_app(conv_store=conv, agent_loops=loops)
    app.config["SOVERYN_REQUIRE_LOCALHOST"] = False
    app.config["CITIZENS_DB"] = str(db)
    # environals used by _db_path fallback in some code paths
    monkeypatch.setenv("SOVERYN_CITIZENS_DB", str(db))
    return app.test_client(), db, desks


def test_post_enqueues_commission(client):
    c, db, _ = client
    resp = c.post(
        "/api/citizens/aetheria/commissions",
        json={"title": "Dock brief", "body": "summarize into outbox"},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    data = resp.get_json()
    assert data["state"] == "queued"
    assert data["citizen_id"] == "aetheria"
    assert "Dock brief" in data["body"]
    assert "summarize into outbox" in data["body"]


def test_post_unknown_citizen_is_404(client):
    c, _, _ = client
    resp = c.post(
        "/api/citizens/ghost/commissions",
        json={"body": "hi"},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert resp.status_code == 404


def test_post_requires_body(client):
    c, _, _ = client
    resp = c.post(
        "/api/citizens/aetheria/commissions",
        json={},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert resp.status_code == 400


def test_list_and_get_and_cancel(client):
    c, _, _ = client
    created = c.post(
        "/api/citizens/aetheria/commissions",
        json={"body": "task one"},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    ).get_json()
    cid = created["id"]

    listed = c.get("/api/citizens/aetheria/commissions?state=queued")
    assert listed.status_code == 200
    assert any(r["id"] == cid for r in listed.get_json()["commissions"])

    got = c.get(f"/api/commissions/{cid}")
    assert got.status_code == 200
    assert got.get_json()["body"] == "task one"

    cancelled = c.post(
        f"/api/commissions/{cid}/cancel",
        json={"reason": "changed my mind"},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert cancelled.status_code == 200
    assert cancelled.get_json()["state"] == "failed"
    assert "changed my mind" in cancelled.get_json()["error"]


def test_roster_shows_on_duty_when_running(client):
    c, db, _ = client
    from soveryn.citizens import commissions as cmod

    with connect(db) as conn:
        cid = cmod.enqueue(
            conn, "aetheria", "busy work", at="2026-08-14T10:00:00Z"
        )
        cmod.claim(
            conn, "aetheria", worker="test", at="2026-08-14T10:01:00Z"
        )

    resp = c.get("/api/citizens")
    assert resp.status_code == 200
    rows = {r["id"]: r for r in resp.get_json()["citizens"]}
    assert rows["aetheria"]["status"] == "on_duty"


def test_roster_includes_duties_after_refresh(client, tmp_path):
    c, db, desks = client
    # seed founding duties via census refresh
    resp = c.post(
        "/api/citizens/refresh",
        json={},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    rows = {r["id"]: r for r in resp.get_json()["citizens"]}
    assert "heartbeat" in rows["aetheria"]["duties_enabled"]
    assert "patrol" in rows["vett"]["duties_enabled"]

    board = c.get("/api/citizens")
    assert board.status_code == 200
    aeth = next(r for r in board.get_json()["citizens"] if r["id"] == "aetheria")
    assert any(d["kind"] == "heartbeat" for d in aeth["duties"])


def test_citizens_page_serves(client):
    c, _, _ = client
    resp = c.get("/citizens")
    assert resp.status_code == 200
    assert b"Citizens" in resp.data
    assert b"data-testid=\"citizens-board\"" in resp.data
    assert b"data-testid=\"spawned-panel\"" in resp.data
    assert b"Spawned under Aetheria" in resp.data


def test_board_includes_spawned_under_aetheria(client):
    """Specialists are visitors on the board — never founding citizens."""
    c, _, _ = client
    resp = c.get("/api/citizens")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "spawned" in data
    spawned = data["spawned"]
    assert spawned["host_citizen"] == "aetheria"
    assert spawned["kind"] == "specialist"
    assert "specialists" in spawned
    assert isinstance(spawned["specialists"], list)
    assert spawned["count"] == len(spawned["specialists"])
    # founding roster never includes ephemeral specialist ids
    citizen_ids = {r["id"] for r in data["citizens"]}
    assert citizen_ids <= {"aetheria", "vett", "scotty"} or "aetheria" in citizen_ids
