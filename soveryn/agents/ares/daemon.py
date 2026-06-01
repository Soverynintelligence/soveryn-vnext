"""Ares daemon surface.

Ares is a background host sentinel, not an LLM chat agent. The daemon runs
hardware collectors, tracks finding lifecycle transitions, and routes findings
through the Ares severity router.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterable
from pathlib import Path

from soveryn.agents.ares import signal_sender
from soveryn.agents.ares.findings import AresFinding, FindingTracker
from soveryn.agents.ares.lanes.architecture import collect_architecture_live
from soveryn.agents.ares.lanes.hardware import collect_cpu_live, collect_drives_live, collect_gpu_live
from soveryn.agents.ares.lanes.network import collect_network_live
from soveryn.agents.ares.router import AresSinks, default_sinks, route_cleared, route_finding
from soveryn.platform.bus import SQLiteBus

DEFAULT_ARES_BUS_PATH = Path("/home/jon-deoliveira/soveryn_vnext/data/ares/ares_bus.sqlite3")
Collector = Callable[[], Iterable[AresFinding]]
Sleep = Callable[[float], None]
StopRequested = Callable[[], bool]


class AresDaemonNotPortedError(NotImplementedError):
    """Backward-compatible exception name from the declared Phase 1 surface."""


class AresDaemonSurface:
    """No-LLM Ares daemon entry surface."""

    agent_name = "ares"
    uses_llm = False

    def __init__(
        self,
        *,
        collectors: Iterable[Collector] | None = None,
        tracker: FindingTracker | None = None,
        sinks: AresSinks | None = None,
        dry_run: bool = True,
    ) -> None:
        self.collectors = tuple(collectors) if collectors is not None else _default_collectors()
        self.tracker = tracker or FindingTracker()
        self.sinks = sinks
        self.dry_run = dry_run

    def scan_once(self) -> tuple[AresFinding, ...]:
        """Run one collector pass and route lifecycle transitions."""

        findings: list[AresFinding] = []
        for collector in self.collectors:
            findings.extend(tuple(collector()))

        result = self.tracker.update(tuple(findings))
        if result.active or result.cleared:
            sinks = self._routed_sinks()
            for event in result.active:
                route_finding(event, sinks)
            for event in result.cleared:
                route_cleared(event, sinks)
        return tuple(findings)

    def run_forever(
        self,
        *,
        interval_seconds: float = 60.0,
        iterations: int | None = None,
        sleep: Sleep = time.sleep,
        stop_requested: StopRequested | None = None,
        shutdown_poll_granularity_seconds: float = 1.0,
    ) -> None:
        """Run the scan loop; `iterations` exists so tests can bound it.

        Sleep between scans is chunked into `shutdown_poll_granularity_seconds`
        slices so a SIGTERM-driven `stop_requested` flip is observed within
        ~one granularity, not at end of the full inter-scan sleep. Python 3.5+
        sleep is non-interruptible (PEP 475 — sleep resumes after signal),
        so without chunking, SIGTERM mid-sleep would wait the full interval.
        """

        should_stop = stop_requested or _never_stop
        completed = 0
        while iterations is None or completed < iterations:
            if should_stop():
                break
            self.scan_once()
            completed += 1
            if iterations is not None and completed >= iterations:
                break
            if should_stop():
                break
            _interruptible_sleep(
                interval_seconds,
                should_stop=should_stop,
                sleep=sleep,
                granularity=shutdown_poll_granularity_seconds,
            )

    def _routed_sinks(self) -> AresSinks:
        sinks = self.sinks or _default_sinks()
        if not self.dry_run:
            return sinks
        return AresSinks(
            telemetry_sink=sinks.telemetry_sink,
            bus_sink=sinks.bus_sink,
            signal_sink=_suppress_signal,
            telemetry_cleared_sink=sinks.telemetry_cleared_sink,
            bus_cleared_sink=sinks.bus_cleared_sink,
        )


def _default_collectors() -> tuple[Collector, ...]:
    return (
        collect_gpu_live,
        collect_cpu_live,
        collect_drives_live,
        collect_network_live,
        collect_architecture_live,
    )


def _default_sinks() -> AresSinks:
    bus = SQLiteBus(_default_bus_path())
    return default_sinks(bus=bus, signal_sender=signal_sender)


def _default_bus_path() -> Path:
    override = os.environ.get("SOVERYN_ARES_BUS_PATH")
    return Path(override) if override else DEFAULT_ARES_BUS_PATH


def _suppress_signal(finding: AresFinding, priority: bool = False) -> None:
    return None


def _never_stop() -> bool:
    return False


def _interruptible_sleep(
    duration_seconds: float,
    *,
    should_stop: StopRequested,
    sleep: Sleep,
    granularity: float = 1.0,
) -> None:
    """Sleep up to `duration_seconds` total, but check `should_stop()`
    every `granularity` seconds and exit early on True. Chunks the call
    to the injected `sleep` so tests can verify both the chunking and
    the early-exit behavior with deterministic fake sleep.
    """
    if duration_seconds <= 0:
        return
    if granularity <= 0:
        granularity = duration_seconds
    elapsed = 0.0
    while elapsed < duration_seconds:
        if should_stop():
            return
        chunk = min(granularity, duration_seconds - elapsed)
        sleep(chunk)
        elapsed += chunk
