"""Tests for /api/system/rig — what is actually running on each GPU."""

from unittest.mock import patch
import subprocess
import pytest

from soveryn.agents.loop import AgentLoop
from soveryn.app.startup import create_app
from soveryn.config.runtime import ACTIVE_AGENTS
from soveryn.inference.llama_server_client import ChatResponse
from soveryn.memory.conversation_store import ConversationStore

GPU_RAW = (
    "2, NVIDIA RTX PRO 5000 Blackwell, GPU-946b08b0-cccc, 45267, 48935, 0, 45\n"
)
APPS_RAW = "46765, 43086, GPU-946b08b0-cccc\n"


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


def test_rig_route_returns_json_shape(client):
    from soveryn.app.services import rig_stats
    rig_stats._cache = None
    with patch("subprocess.run", side_effect=[_smi(GPU_RAW), _smi(APPS_RAW)]), \
         patch("soveryn.app.services.rig_stats._resolve_pid_name", return_value="aetheria"):
        resp = client.get("/api/system/rig")

    assert resp.status_code == 200
    assert resp.is_json
    data = resp.get_json()
    assert data["available"] is True
    assert "message" in data
    assert "fetched_at" in data
    assert len(data["gpus"]) == 1
    gpu = data["gpus"][0]
    assert gpu["index"] == 2
    assert gpu["name"] == "NVIDIA RTX PRO 5000 Blackwell"
    assert gpu["uuid"] == "GPU-946b08b0-cccc"
    assert gpu["mem_used_mib"] == 45267
    assert gpu["mem_total_mib"] == 48935
    assert gpu["util_pct"] == 0
    assert gpu["temp_c"] == 45
    assert gpu["residents"] == [{"name": "aetheria", "mem_mib": 43086}]
    assert data["residents_known"] is True


def test_rig_route_when_smi_missing_returns_200_available_false(client):
    from soveryn.app.services import rig_stats
    rig_stats._cache = None
    with patch("subprocess.run", side_effect=FileNotFoundError()):
        resp = client.get("/api/system/rig")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["available"] is False
    assert data["gpus"] == []
    assert "message" in data


def test_rig_route_exposes_residents_known_false_when_compute_apps_probe_fails(client):
    """The compute-apps probe fails but --query-gpu succeeds: gpus are
    populated (real identity/memory/temp), residents is [] on every gpu, and
    the route must surface residents_known=False so the UI doesn't render
    every card as free capacity."""
    from soveryn.app.services import rig_stats
    rig_stats._cache = None
    with patch("subprocess.run", side_effect=[_smi(GPU_RAW), FileNotFoundError()]):
        resp = client.get("/api/system/rig")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["available"] is True
    assert data["residents_known"] is False
    assert len(data["gpus"]) == 1
    assert data["gpus"][0]["residents"] == []


def test_rig_route_exposes_residents_known_true_when_genuinely_idle(client):
    """The counterpart: compute-apps succeeds and legitimately reports zero
    rows. residents_known must be True here, provably distinct from the
    failure case above even though residents is [] in both."""
    from soveryn.app.services import rig_stats
    rig_stats._cache = None
    with patch("subprocess.run", side_effect=[_smi(GPU_RAW), _smi("", rc=0)]):
        resp = client.get("/api/system/rig")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["available"] is True
    assert data["residents_known"] is True
    assert data["gpus"][0]["residents"] == []
