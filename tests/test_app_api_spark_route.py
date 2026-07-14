"""Tests for /api/system/spark route."""

import subprocess
import urllib.error
from unittest.mock import patch
import pytest

from soveryn.agents.loop import AgentLoop
from soveryn.app.startup import create_app
from soveryn.config.runtime import ACTIVE_AGENTS
from soveryn.inference.llama_server_client import ChatResponse
from soveryn.memory.conversation_store import ConversationStore

from soveryn.app.services import spark_stats


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


PROBE_OK = """45, 52
---
Mem:  129922760704 52613349376 17179869184 0 60129542144 74000000000
---
nemotron-spark|running
"""


def _ssh_ok():
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=PROBE_OK, stderr="")


def _ssh_fail():
    return subprocess.CompletedProcess(args=[], returncode=255, stdout="", stderr="no route")


def _vllm_up_for(reachable_host, model="nemotron"):
    """Reachability side_effect that answers up=True only for one host — used
    to pin which of fabric/wifi is "the one that's actually serving"."""
    def _f(host):
        if host == reachable_host:
            return spark_stats.SparkVllm(up=True, model=model, requests_running=0.0,
                                          requests_waiting=0.0, kv_cache_pct=0.1)
        return spark_stats.SparkVllm(up=False)
    return _f


def test_spark_route_returns_json_on_fabric(client):
    spark_stats._cache = None
    with patch("subprocess.run", return_value=_ssh_ok()), \
         patch("soveryn.app.services.spark_stats._fetch_vllm",
               return_value=spark_stats.SparkVllm(up=True, model="nemotron",
                                                  requests_running=0.0,
                                                  requests_waiting=0.0,
                                                  kv_cache_pct=0.1)):
        resp = client.get("/api/system/spark")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["available"] is True
    assert data["path"] == "fabric"
    assert data["host"]["mem_total_bytes"] == 129922760704
    assert data["containers"][0]["name"] == "nemotron-spark"
    assert data["vllm"]["model"] == "nemotron"
    assert data["host_known"] is True


def test_spark_route_when_unreachable(client):
    spark_stats._cache = None
    with patch("subprocess.run", side_effect=[_ssh_fail(), _ssh_fail()]), \
         patch("soveryn.app.services.spark_stats._fetch_vllm",
               return_value=spark_stats.SparkVllm(up=False)):
        resp = client.get("/api/system/spark")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["available"] is False
    assert data["path"] is None
    assert data["host"] is None
    assert data["message"]
    assert data["host_known"] is False


def test_spark_route_vllm_fabric_but_ssh_fails_is_still_available(client):
    """THE PRODUCTION BUG, exercised through the route: a wedged sshd must
    not paint a healthy, serving Spark as dead. host_known must be False and
    host/containers must degrade — but available/path/vllm must not."""
    spark_stats._cache = None
    with patch("subprocess.run", return_value=_ssh_fail()), \
         patch("soveryn.app.services.spark_stats._fetch_vllm",
               side_effect=_vllm_up_for(spark_stats.SPARK_FABRIC_HOST)):
        resp = client.get("/api/system/spark")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["available"] is True
    assert data["path"] == "fabric"
    assert data["host_known"] is False
    assert data["host"] is None
    assert data["containers"] == []
    assert data["vllm"]["up"] is True
    assert data["vllm"]["model"] == "nemotron"


def test_spark_route_vllm_wifi_only_ssh_fails(client):
    spark_stats._cache = None
    with patch("subprocess.run", return_value=_ssh_fail()), \
         patch("soveryn.app.services.spark_stats._fetch_vllm",
               side_effect=_vllm_up_for(spark_stats.SPARK_WIFI_HOST)):
        resp = client.get("/api/system/spark")
    data = resp.get_json()
    assert data["available"] is True
    assert data["path"] == "wifi"
    assert data["host_known"] is False
    assert data["host"] is None


def test_spark_route_ssh_works_but_vllm_down(client):
    spark_stats._cache = None
    with patch("subprocess.run", return_value=_ssh_ok()), \
         patch("soveryn.app.services.spark_stats._fetch_vllm",
               return_value=spark_stats.SparkVllm(up=False)):
        resp = client.get("/api/system/spark")
    data = resp.get_json()
    assert data["available"] is True
    assert data["host_known"] is True
    assert data["host"]["mem_total_bytes"] == 129922760704
    assert data["vllm"]["up"] is False


def test_spark_route_fabric_preferred_over_wifi_when_both_answer(client):
    spark_stats._cache = None
    with patch("subprocess.run", return_value=_ssh_ok()), \
         patch("soveryn.app.services.spark_stats._fetch_vllm",
               return_value=spark_stats.SparkVllm(up=True, model="nemotron")):
        resp = client.get("/api/system/spark")
    data = resp.get_json()
    assert data["path"] == "fabric"
    assert data["host_known"] is True
