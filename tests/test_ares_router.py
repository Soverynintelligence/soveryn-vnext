"""Tests for pure Ares four-tier routing."""

from __future__ import annotations

from soveryn.agents.ares.findings import AresFinding, FindingEvent, Severity
from soveryn.agents.ares.router import AresSinks, default_sinks, route_cleared, route_finding
from soveryn.platform import telemetry
from soveryn.platform.bus import SQLiteBus


def _finding(severity: Severity) -> AresFinding:
    return AresFinding(
        "gpu.temperature",
        severity,
        {"gpu": 0, "temp_c": 91},
        key=f"gpu0-{severity.value}",
    )


def _sinks() -> tuple[AresSinks, list[tuple[str, object]]]:
    calls: list[tuple[str, object]] = []
    sinks = AresSinks(
        telemetry_sink=lambda finding: calls.append(("telemetry", finding)),
        bus_sink=lambda finding: calls.append(("bus", finding)),
        signal_sink=lambda finding, priority=False: calls.append(("signal", (finding, priority))),
    )
    return sinks, calls


def test_info_routes_to_telemetry_only():
    sinks, calls = _sinks()
    finding = _finding(Severity.INFO)

    route_finding(FindingEvent(finding, is_new=True), sinks)

    assert calls == [("telemetry", finding)]


def test_warning_routes_to_telemetry_and_bus():
    sinks, calls = _sinks()
    finding = _finding(Severity.WARNING)

    route_finding(FindingEvent(finding, is_new=True), sinks)

    assert calls == [("telemetry", finding), ("bus", finding)]


def test_critical_routes_to_telemetry_bus_and_nonpriority_signal():
    sinks, calls = _sinks()
    finding = _finding(Severity.CRITICAL)

    route_finding(FindingEvent(finding, is_new=True), sinks)

    assert calls == [
        ("telemetry", finding),
        ("bus", finding),
        ("signal", (finding, False)),
    ]


def test_emergency_routes_to_telemetry_bus_and_priority_signal():
    sinks, calls = _sinks()
    finding = _finding(Severity.EMERGENCY)

    route_finding(FindingEvent(finding, is_new=True), sinks)

    assert calls == [
        ("telemetry", finding),
        ("bus", finding),
        ("signal", (finding, True)),
    ]


def test_ongoing_findings_do_not_reemit_bus_or_signal():
    sinks, calls = _sinks()
    critical = _finding(Severity.CRITICAL)
    emergency = _finding(Severity.EMERGENCY)

    route_finding(FindingEvent(critical, is_new=False), sinks)
    route_finding(FindingEvent(emergency, is_new=False), sinks)

    assert calls == [("telemetry", critical), ("telemetry", emergency)]


def test_cleared_event_routes_to_telemetry_and_bus_never_signal():
    sinks, calls = _sinks()
    finding = _finding(Severity.EMERGENCY)

    route_cleared(FindingEvent(finding, is_new=False), sinks)

    assert calls == [("telemetry", finding), ("bus", finding)]


class FakeSignalSender:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    def send(self, message: str, *, priority: bool = False):
        self.calls.append((message, priority))


def _platform_sinks(tmp_path, monkeypatch):
    monkeypatch.setenv("SOVERYN_TELEMETRY_DIR", str(tmp_path / "telemetry"))
    bus = SQLiteBus(tmp_path / "ares-bus.sqlite3")
    signal = FakeSignalSender()
    sinks = default_sinks(bus=bus, signal_sender=signal)
    return sinks, bus, signal


def test_default_sinks_route_emergency_to_telemetry_bus_and_priority_signal(tmp_path, monkeypatch):
    sinks, bus, signal = _platform_sinks(tmp_path, monkeypatch)
    finding = _finding(Severity.EMERGENCY)

    route_finding(FindingEvent(finding, is_new=True), sinks)

    telemetry_events = telemetry.query({"source": "ares", "event_type": finding.finding_type})
    bus_events = bus.subscribe(["anomaly.detected"], cursor=0)
    assert len(telemetry_events) == 1
    assert telemetry_events[0].level == "error"
    assert telemetry_events[0].payload == {
        "id": finding.id,
        "finding_type": finding.finding_type,
        "severity": "emergency",
        "evidence": finding.evidence,
        "status": "active",
    }
    assert len(bus_events) == 1
    assert bus_events[0].actor == "ares"
    assert bus_events[0].payload == telemetry_events[0].payload
    assert signal.calls == [("[ARES EMERGENCY] gpu.temperature: {'gpu': 0, 'temp_c': 91}", True)]


def test_default_sinks_route_critical_to_nonpriority_signal(tmp_path, monkeypatch):
    sinks, bus, signal = _platform_sinks(tmp_path, monkeypatch)
    finding = _finding(Severity.CRITICAL)

    route_finding(FindingEvent(finding, is_new=True), sinks)

    telemetry_events = telemetry.query({"source": "ares", "event_type": finding.finding_type})
    bus_events = bus.subscribe(["anomaly.detected"], cursor=0)
    assert telemetry_events[0].level == "error"
    assert telemetry_events[0].payload["severity"] == "critical"
    assert bus_events[0].payload["severity"] == "critical"
    assert signal.calls == [("[ARES CRITICAL] gpu.temperature: {'gpu': 0, 'temp_c': 91}", False)]


def test_default_sinks_route_warning_to_telemetry_and_bus_only(tmp_path, monkeypatch):
    sinks, bus, signal = _platform_sinks(tmp_path, monkeypatch)
    finding = _finding(Severity.WARNING)

    route_finding(FindingEvent(finding, is_new=True), sinks)

    telemetry_events = telemetry.query({"source": "ares", "event_type": finding.finding_type})
    bus_events = bus.subscribe(["anomaly.detected"], cursor=0)
    assert telemetry_events[0].level == "warning"
    assert telemetry_events[0].payload["severity"] == "warning"
    assert bus_events[0].payload["severity"] == "warning"
    assert signal.calls == []


def test_default_sinks_route_info_to_telemetry_only(tmp_path, monkeypatch):
    sinks, bus, signal = _platform_sinks(tmp_path, monkeypatch)
    finding = _finding(Severity.INFO)

    route_finding(FindingEvent(finding, is_new=True), sinks)

    telemetry_events = telemetry.query({"source": "ares", "event_type": finding.finding_type})
    bus_events = bus.subscribe(["anomaly.detected"], cursor=0)
    assert telemetry_events[0].level == "info"
    assert telemetry_events[0].payload["severity"] == "info"
    assert bus_events == ()
    assert signal.calls == []


def test_default_sinks_route_cleared_as_resolution_to_telemetry_and_bus(tmp_path, monkeypatch):
    sinks, bus, signal = _platform_sinks(tmp_path, monkeypatch)
    finding = _finding(Severity.CRITICAL)

    route_cleared(FindingEvent(finding, is_new=False), sinks)

    telemetry_events = telemetry.query({"source": "ares", "event_type": finding.finding_type})
    bus_events = bus.subscribe(["anomaly.detected"], cursor=0)
    assert len(telemetry_events) == 1
    assert telemetry_events[0].level == "error"
    assert telemetry_events[0].payload["status"] == "cleared"
    assert len(bus_events) == 1
    assert bus_events[0].payload["status"] == "cleared"
    assert signal.calls == []
