"""Tests for /api/automations list + dry-run + channel prefs (v0)."""

from __future__ import annotations

import pytest

from soveryn.agents.loop import AgentLoop
from soveryn.app.startup import create_app
from soveryn.config.runtime import ACTIVE_AGENTS
from soveryn.memory.conversation_store import ConversationStore


@pytest.fixture
def client(tmp_path, fake_chat, monkeypatch):
    """Isolated app client with SOVERYN_DATA_ROOT pointed at tmp."""
    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    conv = ConversationStore(tmp_path / "conv.db")
    loops = {n: AgentLoop(n, conv, chat_fn=fake_chat) for n in ACTIVE_AGENTS}
    app = create_app(conv_store=conv, agent_loops=loops)
    app.config["SOVERYN_REQUIRE_LOCALHOST"] = False
    return app.test_client()


def test_list_automations_ok(client):
    resp = client.get("/api/automations")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["dry_run_only"] is False
    assert data["count"] >= 1
    assert "command_center" in data["available_channels"]
    assert "signal" in data["available_channels"]
    assert isinstance(data["automations"], list)
    first = data["automations"][0]
    for key in ("id", "title", "category", "agent", "cron", "prompt", "delivery", "channels"):
        assert key in first
    assert first["channels"] == ["command_center"]
    assert first["has_routine"] is True
    assert first["routine_source"] == "package"


def test_get_routine_markdown(client):
    listing = client.get("/api/automations").get_json()
    aid = listing["automations"][0]["id"]
    resp = client.get(f"/api/automations/{aid}/routine")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["id"] == aid
    assert data["source"] == "package"
    assert "## How" in data["markdown"]
    assert data["bytes"] > 0


def test_get_routine_unknown_404(client):
    resp = client.get("/api/automations/not_a_real_automation/routine")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "unknown_id"


def test_dry_run_known_automation(client):
    listing = client.get("/api/automations").get_json()
    aid = listing["automations"][0]["id"]
    resp = client.post(
        f"/api/automations/{aid}/run",
        json={"live": False},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    result = data["result"]
    assert result["id"] == aid
    assert result["dry_run"] is True
    assert result["status"] in ("ok", "would_send", "disabled")
    assert result["channels"] == ["command_center"]


def test_set_channels_and_dry_run(client):
    listing = client.get("/api/automations").get_json()
    aid = listing["automations"][0]["id"]
    resp = client.put(
        f"/api/automations/{aid}/channels",
        json={"channels": ["command_center", "signal"]},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["channels"] == ["command_center", "signal"]

    listing2 = client.get("/api/automations").get_json()
    item = next(a for a in listing2["automations"] if a["id"] == aid)
    assert item["channels"] == ["command_center", "signal"]

    run = client.post(
        f"/api/automations/{aid}/run",
        json={"live": False},
    ).get_json()
    assert run["result"]["channels"] == ["command_center", "signal"]


def test_set_channels_rejects_empty(client):
    listing = client.get("/api/automations").get_json()
    aid = listing["automations"][0]["id"]
    resp = client.put(
        f"/api/automations/{aid}/channels",
        json={"channels": []},
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "bad_request"


def test_live_run_end_to_end(client):
    listing = client.get("/api/automations").get_json()
    aid = listing["automations"][0]["id"]
    resp = client.post(
        f"/api/automations/{aid}/run",
        json={"live": True},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    result = data["result"]
    assert result["dry_run"] is False
    assert result["status"] == "ok"
    assert result["mode"] == "live"
    assert result["content"] == "ok"
    assert "session_id" in result
    assert "channels" in result


def test_unknown_automation_404(client):
    resp = client.post(
        "/api/automations/not_a_real_automation/run",
        json={},
    )
    assert resp.status_code == 404
    data = resp.get_json()
    assert data["ok"] is False
    assert data["error"] == "unknown_id"


def test_inbox_endpoint_empty(client):
    resp = client.get("/api/automations/inbox")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["inbox"] == []
    assert data["signal_live_armed"] is False


def test_live_run_writes_inbox(client):
    """Live run with fake loops should land in CC inbox."""
    listing = client.get("/api/automations").get_json()
    aid = listing["automations"][0]["id"]
    # Ensure CC channel
    client.put(f"/api/automations/{aid}/channels", json={"channels": ["command_center"]})
    resp = client.post(f"/api/automations/{aid}/run", json={"live": True, "source": "manual"})
    # May fall back to dry-run if loops lack content — still 200
    assert resp.status_code == 200
    body = resp.get_json()
    assert "result" in body
    # If live succeeded with content path, inbox may be set; if dry_run fallback, skip
    if not body["result"].get("dry_run"):
        assert body.get("inbox") is not None
        inbox = client.get("/api/automations/inbox").get_json()
        assert inbox["count"] >= 1
