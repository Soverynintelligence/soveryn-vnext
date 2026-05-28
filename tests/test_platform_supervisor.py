"""Tests for supervisor HealthProbe.check."""

import os
import socket
import time
import urllib.error
from unittest.mock import patch

from soveryn.platform.supervisor import HealthCheck, HealthProbe


class _FakeHTTPResponse:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_http_probe_healthy_target_returns_ok():
    check = HealthCheck("svc", "http://127.0.0.1:1234/health", timeout_seconds=1.5)

    with patch("urllib.request.urlopen", return_value=_FakeHTTPResponse(200)) as m:
        result = HealthProbe().check(check)

    assert result.name == "svc"
    assert result.state == "ok"
    assert result.detail == "HTTP 200"
    assert m.call_args.kwargs["timeout"] == 1.5


def test_http_probe_reachable_unhealthy_target_returns_fail():
    check = HealthCheck("svc", "http://127.0.0.1:1234/health")
    err = urllib.error.HTTPError(check.target, 503, "Service Unavailable", None, None)

    with patch("urllib.request.urlopen", side_effect=err):
        result = HealthProbe().check(check)

    assert result.state == "fail"
    assert result.detail == "HTTP 503"


def test_http_probe_unreachable_target_returns_unknown_not_fail():
    check = HealthCheck("svc", "http://127.0.0.1:9/health")

    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")):
        result = HealthProbe().check(check)

    assert result.state == "unknown"
    assert "unreachable" in result.detail


def test_http_probe_timeout_respects_timeout_and_returns_unknown():
    check = HealthCheck("svc", "http://10.255.255.1/health", timeout_seconds=0.01)

    with patch("urllib.request.urlopen", side_effect=socket.timeout("timed out")) as m:
        result = HealthProbe().check(check)

    assert result.state == "unknown"
    assert m.call_args.kwargs["timeout"] == 0.01


def test_file_heartbeat_probe_fresh_file_returns_ok(tmp_path):
    heartbeat = tmp_path / "ares_daemon_state.json"
    heartbeat.write_text("{}")
    check = HealthCheck("ares", f"file:{heartbeat}:60")

    result = HealthProbe().check(check)

    assert result.state == "ok"
    assert "heartbeat age" in result.detail


def test_file_heartbeat_probe_stale_file_returns_fail(tmp_path):
    heartbeat = tmp_path / "ares_daemon_state.json"
    heartbeat.write_text("{}")
    old = time.time() - 120
    os.utime(heartbeat, (old, old))
    check = HealthCheck("ares", f"file:{heartbeat}:1")

    result = HealthProbe().check(check)

    assert result.state == "fail"
    assert ">" in result.detail


def test_file_heartbeat_probe_missing_file_returns_unknown():
    check = HealthCheck("ares", "file:/tmp/does-not-exist-soveryn-heartbeat:60")

    result = HealthProbe().check(check)

    assert result.state == "unknown"
    assert "missing heartbeat file" in result.detail


def test_unsupported_target_returns_unknown():
    result = HealthProbe().check(HealthCheck("svc", "systemd:aetheria-chat.service"))

    assert result.state == "unknown"
    assert "unsupported target" in result.detail
