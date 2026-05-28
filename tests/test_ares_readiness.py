"""Ares-readiness integration contract for Phase 2 platform APIs."""

from __future__ import annotations

import builtins
import inspect

import pytest

from soveryn.platform import telemetry
from soveryn.platform.bus import SQLiteBus
from soveryn.platform.supervisor.health import HealthCheck, HealthProbe


def test_phase3_ares_daemon_contract_without_llm(monkeypatch, tmp_path):
    monkeypatch.setenv("SOVERYN_TELEMETRY_DIR", str(tmp_path / "telemetry"))
    bus = SQLiteBus(tmp_path / "bus.sqlite3")
    heartbeat_path = tmp_path / "ares_daemon_state.json"
    heartbeat_path.write_text('{"state":"ok"}\n', encoding="utf-8")

    def fake_ares_daemon() -> None:
        bus.publish(
            "anomaly.detected",
            {
                "type": "test_anomaly",
                "severity": "low",
                "evidence": {"source": "phase2-contract"},
            },
            actor="ares",
        )
        telemetry.log(
            source="ares",
            event_type="anomaly.recorded",
            level="info",
            payload={
                "type": "test_anomaly",
                "severity": "low",
                "bus_event": "anomaly.detected",
            },
        )

    assert "platform.inference" not in inspect.getsource(fake_ares_daemon)
    with _guard_platform_inference_import(monkeypatch):
        fake_ares_daemon()

        scotty_seen = bus.subscribe(["anomaly.detected"], cursor=0)
        assert len(scotty_seen) == 1
        assert scotty_seen[0].actor == "ares"
        assert scotty_seen[0].event_type == "anomaly.detected"
        assert scotty_seen[0].payload == {
            "type": "test_anomaly",
            "severity": "low",
            "evidence": {"source": "phase2-contract"},
        }

        probe = HealthProbe()
        healthy = probe.check(HealthCheck(
            name="ares",
            target=f"file:{heartbeat_path}:60",
            timeout_seconds=0.1,
        ))
        unknown = probe.check(HealthCheck(
            name="ares",
            target=f"file:{tmp_path / 'missing_ares_state.json'}:60",
            timeout_seconds=0.1,
        ))

    assert healthy.name == "ares"
    assert healthy.state == "ok"
    assert unknown.name == "ares"
    assert unknown.state == "unknown"

    findings = telemetry.query({"source": "ares"})
    assert len(findings) == 1
    assert findings[0].event_type == "anomaly.recorded"
    assert findings[0].level == "info"
    assert findings[0].payload == {
        "type": "test_anomaly",
        "severity": "low",
        "bus_event": "anomaly.detected",
    }


class _guard_platform_inference_import:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._monkeypatch = monkeypatch
        self._original_import = builtins.__import__

    def __enter__(self) -> None:
        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "soveryn.platform.inference" or name.startswith("soveryn.platform.inference."):
                raise AssertionError(f"Ares readiness contract imported LLM inference module {name}")
            return self._original_import(name, globals, locals, fromlist, level)

        self._monkeypatch.setattr(builtins, "__import__", guarded_import)

    def __exit__(self, exc_type, exc, tb) -> None:
        self._monkeypatch.setattr(builtins, "__import__", self._original_import)
