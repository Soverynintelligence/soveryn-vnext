"""Tests for pure Ares four-tier routing."""

from __future__ import annotations

from soveryn.agents.ares.findings import AresFinding, FindingEvent, Severity
from soveryn.agents.ares.router import AresSinks, route_cleared, route_finding


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
