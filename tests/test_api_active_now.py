"""HTTP smoke for GET /api/active-now."""

from __future__ import annotations

from pathlib import Path

import pytest

from soveryn.agents.loop import AgentLoop
from soveryn.app.startup import create_app
from soveryn.citizens import commissions
from soveryn.citizens.registry import Citizen, connect, register
from soveryn.config.runtime import ACTIVE_AGENTS
from soveryn.inference.llama_server_client import ChatResponse
from soveryn.memory.conversation_store import ConversationStore


@pytest.fixture
def fake_chat():
    return lambda req, server, timeout=60: ChatResponse(
        content="ok",
        finish_reason="stop",
        tool_calls=None,
        usage=None,
        raw={},
    )


def test_active_now_route_empty_and_heartbeat(tmp_path: Path, fake_chat):
    db = tmp_path / "citizens.db"
    with connect(db) as conn:
        register(
            conn,
            Citizen(
                id="aetheria",
                display_name="Aetheria",
                workspace_path=str(tmp_path / "aetheria"),
            ),
        )

    conv = ConversationStore(tmp_path / "conv.db")
    loops = {n: AgentLoop(n, conv, chat_fn=fake_chat) for n in ACTIVE_AGENTS}
    app = create_app(conv_store=conv, agent_loops=loops)
    app.config["CITIZENS_DB"] = str(db)
    client = app.test_client()

    empty = client.get("/api/active-now")
    assert empty.status_code == 200
    assert empty.get_json()["count"] == 0

    with connect(db) as conn:
        commissions.begin_owned(
            conn,
            "aetheria",
            "heartbeat pulse",
            worker="heartbeat",
            at="2026-08-20T15:00:00Z",
        )

    live = client.get("/api/active-now")
    assert live.status_code == 200
    data = live.get_json()
    assert data["count"] >= 1
    assert any(c["kind"] == "heartbeat" and c["citizen"] == "aetheria" for c in data["active"])
