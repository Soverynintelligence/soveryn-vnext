"""Pure four-tier routing for Ares findings."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from soveryn.agents.ares.findings import AresFinding, FindingEvent, Severity

TelemetrySink = Callable[[AresFinding], None]
BusSink = Callable[[AresFinding], None]
SignalSink = Callable[[AresFinding, bool], None]


@dataclass(frozen=True)
class AresSinks:
    """Injectable output sinks used by the pure router."""

    telemetry_sink: TelemetrySink
    bus_sink: BusSink
    signal_sink: SignalSink


def route_finding(event: FindingEvent, sinks: AresSinks) -> None:
    """Route one active finding according to severity and lifecycle state."""

    finding = event.finding
    sinks.telemetry_sink(finding)
    if not event.is_new:
        return

    severity = _normalize_severity(finding.severity)
    if severity is Severity.INFO:
        return
    sinks.bus_sink(finding)
    if severity is Severity.WARNING:
        return
    sinks.signal_sink(finding, severity is Severity.EMERGENCY)


def route_cleared(event: FindingEvent, sinks: AresSinks) -> None:
    """Route one cleared finding resolution."""

    finding = event.finding
    sinks.telemetry_sink(finding)
    sinks.bus_sink(finding)


def _normalize_severity(severity: Severity | str) -> Severity:
    if isinstance(severity, Severity):
        return severity
    return Severity(str(severity).lower().strip())
