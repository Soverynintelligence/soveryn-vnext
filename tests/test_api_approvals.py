"""HTTP surface for Approval Gate pending list + decide."""

from __future__ import annotations

from pathlib import Path

import pytest

from soveryn.agents.loop import AgentLoop
from soveryn.app.startup import create_app
from soveryn.config.runtime import ACTIVE_AGENTS
from soveryn.inference.llama_server_client import ChatResponse
from soveryn.memory.conversation_store import ConversationStore
from soveryn.platform.approval.store import ApprovalBroker, ApprovalStore


@pytest.fixture
def fake_chat():
    return lambda req, server, timeout=60: ChatResponse(
        content="ok",
        finish_reason="stop",
        tool_calls=None,
        usage=None,
        raw={},
    )


@pytest.fixture
def app_with_gate(tmp_path: Path, fake_chat):
    conv = ConversationStore(tmp_path / "conv.db")
    loops = {n: AgentLoop(n, conv, chat_fn=fake_chat) for n in ACTIVE_AGENTS}
    app = create_app(conv_store=conv, agent_loops=loops)
    app.config["SOVERYN_REQUIRE_LOCALHOST"] = False
    store = ApprovalStore(tmp_path / "approvals.db")
    broker = ApprovalBroker(store, ttl_seconds=30.0, poll_interval_seconds=0.01)
    ext = app.extensions.setdefault("soveryn", {})
    ext["approval_broker"] = broker
    return app, broker


def test_house_pending_empty_when_unwired(tmp_path, fake_chat):
    conv = ConversationStore(tmp_path / "conv.db")
    loops = {n: AgentLoop(n, conv, chat_fn=fake_chat) for n in ACTIVE_AGENTS}
    app = create_app(conv_store=conv, agent_loops=loops)
    # Ensure broker absent
    ext = app.extensions.setdefault("soveryn", {})
    ext.pop("approval_broker", None)
    client = app.test_client()
    resp = client.get("/api/approvals/pending")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["count"] == 0
    assert data["approvals"] == []
    assert "note" in data


def test_house_pending_and_decide(app_with_gate):
    app, broker = app_with_gate
    client = app.test_client()
    req = broker.request(
        citizen="aetheria",
        tool="email_send",
        args={"to": "jon@example.com", "subject": "hi"},
        now="2026-08-20T12:00:00",
    )

    resp = client.get("/api/approvals/pending")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["count"] == 1
    assert data["approvals"][0]["id"] == req.id
    assert data["approvals"][0]["tool"] == "email_send"

    per = client.get("/api/citizens/aetheria/approvals")
    assert per.get_json()["count"] == 1

    decided = client.post(
        f"/api/citizens/aetheria/approvals/{req.id}/decision",
        json={"approve": True, "decided_by": "jon"},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert decided.status_code == 200, decided.get_data(as_text=True)
    body = decided.get_json()
    assert body["state"] == "approved"

    after = client.get("/api/approvals/pending")
    assert after.get_json()["count"] == 0
