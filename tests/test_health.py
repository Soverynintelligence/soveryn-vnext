"""Tests for soveryn.inference.health — all probes mocked, no real network calls."""

import socket
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from soveryn.config.runtime import ModelServer, RuntimeService, ServiceEndpoint
from soveryn.inference.health import (
    DEFAULT_TIMEOUT_SECONDS,
    HealthResult,
    check_llama_server,
    check_runtime_service,
    check_service_endpoint,
)

# ─── Fixtures: minimal typed objects for probing ─────────────────────────────

MODEL_SERVER = ModelServer(
    name="test_server",
    port=19999,
    model_path=Path("/mnt/soveryn_models/GGUF/test.gguf"),
)

SERVICE = ServiceEndpoint(
    name="test_service",
    port=19998,
    role="test",
)

PROCESS_SERVICE = RuntimeService(
    name="test_process",
    kind="process",
    launch="user_launched",
)

SCHEDULED_SERVICE = RuntimeService(
    name="test_scheduled",
    kind="scheduled",
    launch="systemd",
)

THREAD_SERVICE = RuntimeService(
    name="test_thread",
    kind="thread",
    launch="app_startup",
)

BAD_KIND_SERVICE = RuntimeService(
    name="test_bad_kind",
    kind="process",  # use a valid kind to pass _validate; we'll override in check
    launch="user_launched",
)


# ─── HealthResult is frozen ───────────────────────────────────────────────────

def test_health_result_is_frozen():
    r = HealthResult("x", "model_server", "ok", 1.5, "fine")
    with pytest.raises((AttributeError, TypeError)):
        r.status = "fail"  # type: ignore[misc]


def test_health_result_fields():
    r = HealthResult("myname", "service_endpoint", "fail", 42.3, "refused")
    assert r.name == "myname"
    assert r.kind == "service_endpoint"
    assert r.status == "fail"
    assert r.latency_ms == pytest.approx(42.3)
    assert r.detail == "refused"


# ─── check_llama_server ───────────────────────────────────────────────────────

class _FakeHTTPResponse:
    """Minimal context-manager mock of urllib.request.urlopen return value."""
    def __init__(self, status: int = 200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_check_llama_server_200_ok():
    with patch("urllib.request.urlopen", return_value=_FakeHTTPResponse(200)):
        result = check_llama_server(MODEL_SERVER, timeout=1.0)
    assert result.name == "test_server"
    assert result.kind == "model_server"
    assert result.status == "ok"
    assert "HTTP 200" in result.detail
    assert result.latency_ms >= 0.0


def test_check_llama_server_500_fail():
    with patch("urllib.request.urlopen", return_value=_FakeHTTPResponse(500)):
        result = check_llama_server(MODEL_SERVER, timeout=1.0)
    assert result.status == "fail"
    assert "HTTP 500" in result.detail


def test_check_llama_server_url_error():
    import urllib.error
    with patch("urllib.request.urlopen",
               side_effect=urllib.error.URLError("Connection refused")):
        result = check_llama_server(MODEL_SERVER, timeout=1.0)
    assert result.status == "fail"
    assert "URLError" in result.detail


def test_check_llama_server_timeout():
    with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
        result = check_llama_server(MODEL_SERVER, timeout=0.01)
    assert result.status == "fail"
    assert "timeout" in result.detail


def test_check_llama_server_socket_timeout():
    with patch("urllib.request.urlopen", side_effect=socket.timeout("timed out")):
        result = check_llama_server(MODEL_SERVER, timeout=0.01)
    assert result.status == "fail"
    assert "timeout" in result.detail


def test_check_llama_server_unexpected_exception():
    with patch("urllib.request.urlopen", side_effect=RuntimeError("unexpected")):
        result = check_llama_server(MODEL_SERVER, timeout=1.0)
    assert result.status == "fail"
    assert "RuntimeError" in result.detail


# ─── check_service_endpoint ───────────────────────────────────────────────────

class _FakeSocket:
    """Context-manager that simulates a successful TCP connection."""
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_check_service_endpoint_ok():
    with patch("socket.create_connection", return_value=_FakeSocket()):
        result = check_service_endpoint(SERVICE, timeout=1.0)
    assert result.name == "test_service"
    assert result.kind == "service_endpoint"
    assert result.status == "ok"
    assert "19998" in result.detail


def test_check_service_endpoint_connection_refused():
    with patch("socket.create_connection",
               side_effect=ConnectionRefusedError("refused")):
        result = check_service_endpoint(SERVICE, timeout=1.0)
    assert result.status == "fail"
    assert "ConnectionRefusedError" in result.detail


def test_check_service_endpoint_socket_timeout():
    with patch("socket.create_connection",
               side_effect=socket.timeout("timed out")):
        result = check_service_endpoint(SERVICE, timeout=0.01)
    assert result.status == "fail"
    assert "timeout" in result.detail


def test_check_service_endpoint_timeout_error():
    with patch("socket.create_connection", side_effect=TimeoutError("timed out")):
        result = check_service_endpoint(SERVICE, timeout=0.01)
    assert result.status == "fail"
    assert "timeout" in result.detail


def test_check_service_endpoint_os_error():
    with patch("socket.create_connection",
               side_effect=OSError("network unreachable")):
        result = check_service_endpoint(SERVICE, timeout=1.0)
    assert result.status == "fail"
    assert "OSError" in result.detail


# ─── check_runtime_service — thread ──────────────────────────────────────────

def test_check_runtime_service_thread_is_deferred():
    result = check_runtime_service(THREAD_SERVICE, timeout=1.0)
    assert result.status == "deferred"
    assert result.latency_ms == 0.0
    assert "in-process thread" in result.detail


# ─── check_runtime_service — process (pgrep) ─────────────────────────────────

def _pgrep_result(returncode: int, stdout: str) -> MagicMock:
    mock = MagicMock()
    mock.returncode = returncode
    mock.stdout = stdout
    mock.stderr = ""
    return mock


def test_check_runtime_service_process_ok():
    with patch("subprocess.run", return_value=_pgrep_result(0, "12345 test_process\n")):
        result = check_runtime_service(PROCESS_SERVICE, timeout=1.0)
    assert result.status == "ok"
    assert "matching process" in result.detail


def test_check_runtime_service_process_no_match():
    with patch("subprocess.run", return_value=_pgrep_result(1, "")):
        result = check_runtime_service(PROCESS_SERVICE, timeout=1.0)
    assert result.status == "fail"
    assert "no matching process" in result.detail


def test_check_runtime_service_process_pgrep_missing():
    with patch("subprocess.run", side_effect=FileNotFoundError("pgrep not found")):
        result = check_runtime_service(PROCESS_SERVICE, timeout=1.0)
    assert result.status == "fail"
    assert "pgrep not installed" in result.detail


def test_check_runtime_service_process_pgrep_timeout():
    with patch("subprocess.run",
               side_effect=subprocess.TimeoutExpired(cmd=["pgrep"], timeout=1.0)):
        result = check_runtime_service(PROCESS_SERVICE, timeout=1.0)
    assert result.status == "fail"
    assert "timeout" in result.detail


# ─── check_runtime_service — scheduled (systemctl) ───────────────────────────

def _systemctl_result(returncode: int) -> MagicMock:
    mock = MagicMock()
    mock.returncode = returncode
    mock.stdout = "active" if returncode == 0 else "inactive"
    mock.stderr = ""
    return mock


def test_check_runtime_service_scheduled_active():
    with patch("subprocess.run", return_value=_systemctl_result(0)):
        result = check_runtime_service(SCHEDULED_SERVICE, timeout=1.0)
    assert result.status == "ok"
    assert "active" in result.detail


def test_check_runtime_service_scheduled_no_active_timer():
    with patch("subprocess.run", return_value=_systemctl_result(1)):
        result = check_runtime_service(SCHEDULED_SERVICE, timeout=1.0)
    assert result.status == "fail"
    assert "no active timer" in result.detail


def test_check_runtime_service_scheduled_systemctl_missing():
    with patch("subprocess.run", side_effect=FileNotFoundError("systemctl not found")):
        result = check_runtime_service(SCHEDULED_SERVICE, timeout=1.0)
    assert result.status == "fail"
    assert "systemctl not installed" in result.detail


def test_check_runtime_service_scheduled_timeout_skips_then_fails():
    """TimeoutExpired on every systemctl call → eventually returns fail."""
    with patch("subprocess.run",
               side_effect=subprocess.TimeoutExpired(cmd=["systemctl"], timeout=1.0)):
        result = check_runtime_service(SCHEDULED_SERVICE, timeout=1.0)
    assert result.status == "fail"


# ─── check_runtime_service — bad kind ────────────────────────────────────────

def test_check_runtime_service_unknown_kind():
    """We construct an ad-hoc service bypassing the dataclass validator."""
    # We can't use RuntimeService directly with a bad kind (frozen dataclass
    # allows it; _validate only runs at module level for the constants).
    bad = RuntimeService(name="bad", kind="unknown_kind",
                         launch="user_launched", role="")
    result = check_runtime_service(bad, timeout=1.0)
    assert result.status == "fail"
    assert "unknown kind" in result.detail


# ─── DEFAULT_TIMEOUT_SECONDS ──────────────────────────────────────────────────

def test_default_timeout_is_2_seconds():
    assert DEFAULT_TIMEOUT_SECONDS == 2.0
