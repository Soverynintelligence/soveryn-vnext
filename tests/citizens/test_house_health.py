"""House health assembly + HTTP surface."""
from __future__ import annotations

from pathlib import Path

import pytest

from soveryn.agents.loop import AgentLoop
from soveryn.app.startup import create_app
from soveryn.citizens.house_health import (
    VOCABULARY,
    assemble_house_health,
    desk_status,
)
from soveryn.citizens.registry import Citizen, connect, observe, register
from soveryn.config.runtime import ACTIVE_AGENTS
from soveryn.inference.llama_server_client import ChatResponse
from soveryn.memory.conversation_store import ConversationStore


def test_vocabulary_pins_peer_and_subagent():
    assert "peer" in VOCABULARY
    assert "subagent" in VOCABULARY
    assert "commission" in VOCABULARY
    assert "soul" in VOCABULARY["peer"]["means"].lower() or "desk" in VOCABULARY["peer"]["means"].lower()
    assert "ephemeral" in VOCABULARY["subagent"]["means"].lower()


def test_desk_status_missing_workspace():
    s = desk_status(None)
    assert s["ok"] is False


def test_desk_status_complete(tmp_path):
    root = tmp_path / "scotty"
    for d in ("inbox", "outbox", "work", "notes"):
        (root / d).mkdir(parents=True)
    s = desk_status(str(root))
    assert s["ok"] is True
    assert s["missing"] == []


def test_assemble_without_registry(tmp_path):
    doc = assemble_house_health(
        db_path=tmp_path / "missing.db",
        agent_loops=["aetheria", "scotty"],
        version="test",
        probe_workers=False,
        now="2026-08-14T12:00:00Z",
    )
    assert doc["app"] == "soveryn"
    assert doc["surface"] == "house"
    assert doc["runtime"]["agent_loops"] == ["aetheria", "scotty"]
    assert doc["runtime"]["sandbox"] == "desk_workspace"
    assert doc["registry"]["ok"] is False
    assert doc["ok"] is False
    assert "vocabulary" in doc
    assert doc["as_of"] == "2026-08-14T12:00:00Z"


def test_assemble_with_registry(tmp_path):
    db = tmp_path / "citizens.db"
    desk = tmp_path / "desks" / "aetheria"
    for d in ("inbox", "outbox", "work", "notes"):
        (desk / d).mkdir(parents=True)
    with connect(db) as conn:
        register(
            conn,
            Citizen(
                id="aetheria",
                display_name="Aetheria",
                workspace_path=str(desk),
            ),
        )
        observe(conn, "aetheria", "present", at="2026-08-14T08:00:00Z")

    def fake_runner(cmd, **kwargs):
        class R:
            stdout = "inactive\n"
            stderr = ""
        return R()

    doc = assemble_house_health(
        db_path=db,
        agent_loops=["aetheria", "vett", "scotty"],
        probe_workers=True,
        runner=fake_runner,
    )
    assert doc["registry"]["ok"] is True
    assert doc["residents"]["counts"].get("resident", 0) >= 1
    assert doc["desks"]["aetheria"]["ok"] is True
    assert "scotty" in doc["workers"]
    assert doc["workers"]["scotty"]["residence"] == "process"


@pytest.fixture
def client(tmp_path, monkeypatch):
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
        observe(conn, "aetheria", "present", at="2026-08-14T08:00:00Z")

    conv = ConversationStore(tmp_path / "conv.db")
    fake = lambda req, server, timeout=60: ChatResponse(
        content="ok", finish_reason="stop", tool_calls=None, usage=None, raw={}
    )
    loops = {n: AgentLoop(n, conv, chat_fn=fake) for n in ACTIVE_AGENTS}
    app = create_app(conv_store=conv, agent_loops=loops)
    app.config["CITIZENS_DB"] = str(db)
    monkeypatch.setenv("SOVERYN_CITIZENS_DB", str(db))
    return app.test_client()


def test_http_house_health(client):
    resp = client.get("/api/citizens/health?probe=0")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["surface"] == "house"
    assert data["runtime"]["kind"] == "soveryn_vnext"
    assert "aetheria" in data["runtime"]["agent_loops"]
    assert data["vocabulary"]["peer"]["name"] == "peer"
    assert data["registry"]["ok"] is True
