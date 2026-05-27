"""Supervisor health-check interface declarations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

HealthState = Literal["ok", "degraded", "fail", "unknown"]


@dataclass(frozen=True)
class HealthCheck:
    """One named health check target."""

    name: str
    target: str
    timeout_seconds: float = 30.0


@dataclass(frozen=True)
class HealthCheckResult:
    """Result shape returned by supervisor health probes."""

    name: str
    state: HealthState
    detail: str = ""


class HealthProbe:
    """Declared health probe interface; execution is implemented later."""

    def check(self, check: HealthCheck) -> HealthCheckResult:
        raise NotImplementedError("Supervisor health probes are declared, not implemented in Phase 1")
