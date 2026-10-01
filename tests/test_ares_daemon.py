"""Tests for the Ares daemon scan loop."""

from __future__ import annotations

import builtins
import inspect

import pytest

from soveryn.agents.ares.daemon import AresDaemonSurface, _default_collectors
from soveryn.agents.ares.findings import AresFinding, FindingTracker, Severity
from soveryn.agents.ares.router import AresSinks


def test_scan_once_routes_hardware_findings_through_tracker_and_sinks(tmp_path):
    warning = AresFinding("drive.space", Severity.WARNING, {"path": "/", "free_pct": 12}, key="/")
    critical = AresFinding("cpu.mce", Severity.CRITICAL, {"corrected": False}, key="mce0")
    calls = {"telemetry": [], "bus": [], "signal": []}
    current = [[warning], [critical]]

    surface = AresDaemonSurface(
        collectors=[lambda: current[0], lambda: current[1]],
        tracker=FindingTracker(tmp_path / "ares_state.json"),
        sinks=_recording_sinks(calls),
        dry_run=False,
    )

    findings = surface.scan_once()

    assert findings == (warning, critical)
    assert calls["telemetry"] == [critical, warning]
    assert calls["bus"] == [critical, warning]
    assert calls["signal"] == [(critical, {"bypass_quiet_hours": True, "bypass_rate_cap": False})]

    current[:] = [[], []]
    assert surface.scan_once() == ()
    assert calls["telemetry"] == [critical, warning, critical, warning]
    assert calls["bus"] == [critical, warning, critical, warning]
    assert calls["signal"] == [(critical, {"bypass_quiet_hours": True, "bypass_rate_cap": False})]


def test_dry_run_suppresses_signal_but_keeps_telemetry_and_bus(tmp_path):
    critical = AresFinding("cpu.mce", Severity.CRITICAL, {"corrected": False}, key="mce0")
    emergency = AresFinding("host.power", Severity.EMERGENCY, {"state": "unstable"}, key="ups")
    calls = {"telemetry": [], "bus": [], "signal": []}

    surface = AresDaemonSurface(
        collectors=[lambda: [critical, emergency]],
        tracker=FindingTracker(tmp_path / "ares_state.json"),
        sinks=_recording_sinks(calls),
        dry_run=True,
    )

    assert surface.scan_once() == (critical, emergency)
    assert calls["telemetry"] == [critical, emergency]
    assert calls["bus"] == [critical, emergency]
    assert calls["signal"] == []


def test_live_mode_allows_signal_for_critical_and_emergency(tmp_path):
    critical = AresFinding("cpu.mce", Severity.CRITICAL, {"corrected": False}, key="mce0")
    emergency = AresFinding("host.power", Severity.EMERGENCY, {"state": "unstable"}, key="ups")
    calls = {"telemetry": [], "bus": [], "signal": []}

    AresDaemonSurface(
        collectors=[lambda: [critical, emergency]],
        tracker=FindingTracker(tmp_path / "ares_state.json"),
        sinks=_recording_sinks(calls),
        dry_run=False,
    ).scan_once()

    assert calls["signal"] == [(critical, {"bypass_quiet_hours": True, "bypass_rate_cap": False}), (emergency, {"bypass_quiet_hours": True, "bypass_rate_cap": True})]


def test_ares_daemon_scan_once_keeps_no_llm_boundary(monkeypatch, tmp_path):
    finding = AresFinding("gpu.status", Severity.INFO, {"index": 0}, key="gpu0")
    calls = {"telemetry": [], "bus": [], "signal": []}
    surface = AresDaemonSurface(
        collectors=[lambda: [finding]],
        tracker=FindingTracker(tmp_path / "ares_state.json"),
        sinks=_recording_sinks(calls),
    )

    assert AresDaemonSurface.uses_llm is False
    assert "platform.inference" not in inspect.getsource(AresDaemonSurface.scan_once)
    with _guard_platform_inference_import(monkeypatch):
        assert surface.scan_once() == (finding,)


def test_run_forever_can_be_bounded_for_scheduler_tests(tmp_path):
    calls = {"scan": 0, "sleep": []}
    surface = AresDaemonSurface(
        collectors=[lambda: []],
        tracker=FindingTracker(tmp_path / "ares_state.json"),
        sinks=_recording_sinks({"telemetry": [], "bus": [], "signal": []}),
    )

    def scan_once():
        calls["scan"] += 1
        return ()

    surface.scan_once = scan_once
    surface.run_forever(interval_seconds=2.5, iterations=3, sleep=calls["sleep"].append)

    # Sleep is chunked into granularity-sized pieces (default 1.0s) so SIGTERM
    # mid-sleep can be observed within ~1s instead of waiting full interval.
    # Two inter-scan gaps × 2.5s = 5.0s total sleep regardless of chunking.
    assert calls["scan"] == 3
    assert sum(calls["sleep"]) == pytest.approx(5.0)
    # And the chunking shape: 1.0 + 1.0 + 0.5 per gap, twice.
    assert calls["sleep"] == [1.0, 1.0, 0.5, 1.0, 1.0, 0.5]


def test_run_forever_exits_promptly_when_stop_requested_mid_sleep(tmp_path):
    """The actual bug from 2026-05-31: SIGTERM mid-sleep set the shutdown
    flag but Python's time.sleep (PEP 475) waited the full interval before
    the loop checked again — up to 60s shutdown lag. The chunked sleep
    polls stop_requested every ~granularity, so shutdown lag is bounded."""
    calls = {"scan": 0, "sleep_calls": 0}
    surface = AresDaemonSurface(
        collectors=[lambda: []],
        tracker=FindingTracker(tmp_path / "ares_state.json"),
        sinks=_recording_sinks({"telemetry": [], "bus": [], "signal": []}),
    )

    def scan_once():
        calls["scan"] += 1
        return ()

    surface.scan_once = scan_once

    # Stop flag flips True after the 3rd sleep chunk.
    flip_at_chunk = 3
    def fake_sleep(secs):
        calls["sleep_calls"] += 1

    stop = {"flag": False}
    def should_stop():
        if calls["sleep_calls"] >= flip_at_chunk:
            stop["flag"] = True
        return stop["flag"]

    surface.run_forever(
        interval_seconds=60.0,
        sleep=fake_sleep,
        stop_requested=should_stop,
    )

    # Daemon ran exactly 1 scan, then started sleeping. Stop flipped at chunk 3
    # of the first inter-scan gap → daemon exits without starting scan #2.
    assert calls["scan"] == 1
    # Only the chunks before the stop check fired: 3 chunks of 1s each.
    assert calls["sleep_calls"] == flip_at_chunk


def test_interruptible_sleep_helper_polls_stop_every_granularity(tmp_path):
    """Direct unit test of the helper: with a should_stop that returns True
    after the third poll, the helper exits early after 3 sleep chunks even
    though duration is much larger."""
    from soveryn.agents.ares.daemon import _interruptible_sleep

    polls = {"n": 0}
    def should_stop():
        polls["n"] += 1
        return polls["n"] >= 3
    sleeps = []
    _interruptible_sleep(
        duration_seconds=60.0,
        should_stop=should_stop,
        sleep=sleeps.append,
        granularity=1.0,
    )
    # Polls: 1 (returns False), then sleep, then 2 (False), then sleep, then
    # 3 (True) → return. So 2 sleep chunks of 1.0 fired.
    assert sleeps == [1.0, 1.0]


def test_interruptible_sleep_zero_duration_returns_immediately():
    from soveryn.agents.ares.daemon import _interruptible_sleep
    sleeps = []
    _interruptible_sleep(
        duration_seconds=0.0,
        should_stop=lambda: False,
        sleep=sleeps.append,
        granularity=1.0,
    )
    assert sleeps == []


def test_default_collectors_include_network_and_architecture_lanes():
    collectors = _default_collectors()
    names = {getattr(c, "__name__", repr(c)) for c in collectors}
    assert "collect_gpu_live" in names
    assert "collect_cpu_live" in names
    assert "collect_drives_live" in names
    assert "collect_network_live" in names
    assert "collect_listeners_live" not in names
    assert "collect_service_presence_live" not in names
    assert "collect_architecture_live" in names


def test_unified_network_live_runs_ss_once_per_call(monkeypatch):
    import soveryn.agents.ares.lanes.network as net

    calls: list = []

    def fake_check_output(cmd, **kwargs):
        calls.append(tuple(cmd))
        return (
            'LISTEN 0 4096 127.0.0.1:5001  0.0.0.0:* users:(("python3.11",pid=1,fd=1))\n'
        )

    monkeypatch.setattr(net.subprocess, "check_output", fake_check_output)
    findings = net.collect_network_live()
    assert len(calls) == 1
    assert any(
        f.finding_type == "network.service_missing" and f.evidence["port"] == 8090
        for f in findings
    )


def test_dry_run_default_still_suppresses_signal_with_new_lanes(tmp_path):
    state_path = tmp_path / "ares_state.json"
    tracker = FindingTracker(state_path=state_path)
    signal_calls: list = []
    sinks = AresSinks(
        telemetry_sink=lambda f: None,
        bus_sink=lambda f: None,
        signal_sink=lambda f, priority=False: signal_calls.append((f, priority)),
    )

    def fake_emergency_collector():
        return [AresFinding(
            "network.public_listener_unallowlisted",
            Severity.EMERGENCY,
            {"bind_address": "0.0.0.0", "port": 4444, "process": "nc"},
        )]

    daemon = AresDaemonSurface(
        collectors=[fake_emergency_collector],
        tracker=tracker,
        sinks=sinks,
        dry_run=True,
    )
    daemon.scan_once()
    assert signal_calls == []


def _recording_sinks(calls: dict[str, list]) -> AresSinks:
    return AresSinks(
        telemetry_sink=calls["telemetry"].append,
        bus_sink=calls["bus"].append,
        signal_sink=lambda finding, priority=False, **brakes: calls["signal"].append(
            (finding, brakes)
        ),
    )


class _guard_platform_inference_import:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._monkeypatch = monkeypatch
        self._original_import = builtins.__import__

    def __enter__(self) -> None:
        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "soveryn.platform.inference" or name.startswith("soveryn.platform.inference."):
                raise AssertionError(f"Ares daemon imported LLM inference module {name}")
            return self._original_import(name, globals, locals, fromlist, level)

        self._monkeypatch.setattr(builtins, "__import__", guarded_import)

    def __exit__(self, exc_type, exc, tb) -> None:
        self._monkeypatch.setattr(builtins, "__import__", self._original_import)
