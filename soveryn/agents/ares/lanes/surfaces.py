"""Ares lane: is the thing we claim to be running actually running?

Added 2026-08-07. On that morning Ares held 53 active findings and every single
one was `architecture.raw_io_in_agents` — a lint rule about import statements —
while Atticus served 404s, the Telegram bridge logged 13,000 errors a day, and
Aetheria's backend crashed twice a week. Ares was not broken. It was pointed at
code style, and nothing was pointed at liveness.

This lane emits three finding types, and the ordering matters because the noise
is what buried the signal last time:

  surface.down            CRITICAL  declared, probed, and wrong
  surface.never_verified  CRITICAL  declared and never once confirmed working
  surface.unknown         WARNING   could not probe — explicitly not an all-clear
  surface.stale           WARNING   last confirmed working too long ago

`never_verified` is CRITICAL on purpose. It is the Atticus case: not a check
that failed, but a surface no one was ever looking at. "We have no idea" and "it
is broken" carry the same risk, and only one of them announces itself.

Follows the partial-scan rule established on 2026-08-02: if the probe pass
cannot run at all, this lane RAISES rather than returning an empty list. An
empty list from a collector means "nothing wrong," and a lane that cannot see
must never say that.
"""
from __future__ import annotations

from soveryn.agents.ares.findings import AresFinding, Severity
from soveryn.platform.surfaces import registry
from soveryn.platform.surfaces.probe import Status, probe_all
from soveryn.platform.surfaces.staleness import Observations


class SurfaceProbeError(RuntimeError):
    """The probe pass itself failed. Distinct from 'everything is fine'."""


# Consecutive bad probes before a surface is reported. In-memory and reset by a
# daemon restart, which is the right trade: after a restart the first genuine
# failure takes two scans (~2 min at the 60s interval) to surface, and nothing
# is lost that a second look would not confirm.
FAIL_STREAK = 2
_STREAK: dict[str, int] = {}


def collect(*, observations: Observations | None = None,
            surfaces=None, timeout: float = 20.0) -> tuple[AresFinding, ...]:
    surfaces = tuple(surfaces if surfaces is not None else registry.live())
    if not surfaces:
        raise SurfaceProbeError("no surfaces declared — the registry is empty, "
                                "which is not the same as everything being healthy")

    obs = observations or Observations()
    try:
        results = probe_all(surfaces, timeout=timeout)
    except Exception as exc:                      # pragma: no cover - defensive
        raise SurfaceProbeError(f"probe pass failed: {type(exc).__name__}: {exc}") from exc

    obs.record(results)
    findings: list[AresFinding] = []

    for r in results:
        if r.status is Status.HEALTHY:
            _STREAK.pop(r.surface, None)
            continue

        # A single bad probe is not an outage. On 2026-08-09 this lane fired
        # CRITICAL to Signal four times in twelve minutes for atticus,
        # soverynintelligence and pondwright-estimator — every one of which was
        # healthy on the next scan. The cause was a serial probe pass taking 41s
        # against a 60s interval, so any latency bump tripped a 20s timeout.
        # The pass is parallel now, but the tolerance belongs here regardless:
        # an alert that cries wolf gets muted, and a muted Ares is how 53 lint
        # findings sat unread while real outages ran underneath.
        _STREAK[r.surface] = _STREAK.get(r.surface, 0) + 1
        if _STREAK[r.surface] < FAIL_STREAK:
            continue

        if r.status is Status.FAILED:
            findings.append(AresFinding(
                "surface.down", Severity.CRITICAL,
                {"surface": r.surface, "detail": r.detail,
                 "failed_checks": _STREAK[r.surface],
                 "latency_s": round(r.latency_s, 3)},
                key=r.surface))
        elif r.status is Status.UNKNOWN:
            findings.append(AresFinding(
                "surface.unknown", Severity.WARNING,
                {"surface": r.surface, "detail": r.detail,
                 "failed_checks": _STREAK[r.surface],
                 "note": "probe could not run — this is NOT evidence the surface "
                         "is healthy"},
                key=r.surface))

    for s in obs.stale(surfaces):
        if s.never:
            findings.append(AresFinding(
                "surface.never_verified", Severity.CRITICAL,
                {"surface": s.surface,
                 "note": "declared but never once confirmed working — the Atticus "
                         "case: not a failing check, an absent one"},
                key=s.surface))
        else:
            findings.append(AresFinding(
                "surface.stale", Severity.WARNING,
                {"surface": s.surface, "age_s": round(s.age_s or 0.0),
                 "interval_s": s.interval_s,
                 "note": "no successful verification recently"},
                key=s.surface))

    return tuple(findings)
