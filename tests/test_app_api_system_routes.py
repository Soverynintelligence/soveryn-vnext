"""Tests for /api/system/gpu route."""

from unittest.mock import patch
import subprocess
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
def client(tmp_path, fake_chat):
    conv = ConversationStore(tmp_path / "conv.db")
    loops = {n: AgentLoop(n, conv, chat_fn=fake_chat) for n in ACTIVE_AGENTS}
    app = create_app(conv_store=conv, agent_loops=loops)
    app.config["SOVERYN_REQUIRE_LOCALHOST"] = False
    return app.test_client()


def _smi(stdout: str = "", rc: int = 0):
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr="")


def test_gpu_route_returns_json(client):
    with patch("subprocess.run", return_value=_smi("0, 10, 50, 5.0, 49152\n")):
        # Force fresh cache by clearing the in-process cache value
        from soveryn.app.services import gpu_stats
        gpu_stats._cache = None
        resp = client.get("/api/system/gpu")
    assert resp.status_code == 200
    assert resp.is_json
    data = resp.get_json()
    assert data["available"] is True
    assert len(data["gpus"]) == 1
    assert data["gpus"][0]["index"] == 0
    assert data["gpus"][0]["util_pct"] == 10


def test_gpu_route_when_smi_missing(client):
    with patch("subprocess.run", side_effect=FileNotFoundError()):
        from soveryn.app.services import gpu_stats
        gpu_stats._cache = None
        resp = client.get("/api/system/gpu")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["available"] is False
    assert data["gpus"] == []
    assert "message" in data
