"""Pure four-tier routing for Ares findings."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from soveryn.agents.ares.findings import AresFinding, FindingEvent, Severity

logger = logging.getLogger("soveryn.agents.ares.router")

TelemetrySink = Callable[[AresFinding], None]
BusSink = Callable[[AresFinding], None]
# Keyword-only brakes now, not one positional bool — see signal_sink.
SignalSink = Callable[..., None]


@dataclass(frozen=True)
class AresSinks:
    """Injectable output sinks used by the pure router."""

    telemetry_sink: TelemetrySink
    bus_sink: BusSink
    signal_sink: SignalSink
    telemetry_cleared_sink: TelemetrySink | None = None
    bus_cleared_sink: BusSink | None = None


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
    # Only CRITICAL and EMERGENCY reach this line — WARNING returned above. Both
    # are worth waking someone for, so both bypass quiet hours; that is the fix
    # for 2026-08-10, when quiet hours silently ate 37 minutes of CRITICAL
    # surface.down. Only EMERGENCY escapes the rate cap, because the cap is flap
    # protection and a flapping surface paged four times in twelve minutes on
    # 2026-08-07.
    sinks.signal_sink(
        finding,
        bypass_quiet_hours=True,
        bypass_rate_cap=severity is Severity.EMERGENCY,
    )


def route_cleared(event: FindingEvent, sinks: AresSinks) -> None:
    """Route one cleared finding resolution."""

    finding = event.finding
    telemetry = sinks.telemetry_cleared_sink or sinks.telemetry_sink
    bus = sinks.bus_cleared_sink or sinks.bus_sink
    telemetry(finding)
    bus(finding)


def _normalize_severity(severity: Severity | str) -> Severity:
    if isinstance(severity, Severity):
        return severity
    return Severity(str(severity).lower().strip())


def default_sinks(*, bus, signal_sender) -> AresSinks:
    """Build real platform-backed sinks for Ares output."""

    return AresSinks(
        telemetry_sink=telemetry_sink,
        bus_sink=lambda finding: bus_sink(finding, bus=bus),
        signal_sink=lambda finding, priority=False, **brakes: signal_sink(
            finding, signal_sender=signal_sender, priority=priority, **brakes
        ),
        telemetry_cleared_sink=lambda finding: telemetry_sink(finding, status="cleared"),
        bus_cleared_sink=lambda finding: bus_sink(finding, bus=bus, status="cleared"),
    )


def telemetry_sink(finding: AresFinding, *, status: str = "active") -> None:
    from soveryn.platform import telemetry

    telemetry.log(
        source="ares",
        event_type=finding.finding_type,
        level=_telemetry_level(finding.severity),
        payload=_payload(finding, status=status),
    )


def bus_sink(finding: AresFinding, *, bus, status: str = "active") -> None:
    bus.publish(
        "anomaly.detected",
        _payload(finding, status=status),
        actor="ares",
    )


def signal_sink(
    finding: AresFinding,
    *,
    signal_sender,
    priority: bool = False,
    bypass_quiet_hours: bool = False,
    bypass_rate_cap: bool = False,
) -> None:
    result = signal_sender.send(
        _signal_message(finding),
        priority=priority,
        bypass_quiet_hours=bypass_quiet_hours,
        bypass_rate_cap=bypass_rate_cap,
    )
    # A dropped alert used to be perfectly silent — send() returned its reason and
    # nobody read it. That is how 37 minutes of CRITICAL went unnoticed on
    # 2026-08-10: the detection worked, the delivery did not, and nothing said so.
    if result is not None and not getattr(result, "sent", True):
        logger.warning(
            "ares finding %s NOT sent to Signal: %s",
            getattr(finding, "id", "?"),
            getattr(result, "reason", "unknown"),
        )


def _payload(finding: AresFinding, *, status: str) -> dict:
    return {
        "id": finding.id,
        "finding_type": finding.finding_type,
        "severity": _severity_value(finding.severity),
        "evidence": finding.evidence,
        "status": status,
    }


def _telemetry_level(severity: Severity | str) -> str:
    normalized = _normalize_severity(severity)
    if normalized is Severity.INFO:
        return "info"
    if normalized is Severity.WARNING:
        return "warning"
    return "error"


def _severity_value(severity: Severity | str) -> str:
    return _normalize_severity(severity).value


def _signal_message(finding: AresFinding) -> str:
    severity = _severity_value(finding.severity).upper()
    return f"[ARES {severity}] {finding.finding_type}: {finding.evidence}"
