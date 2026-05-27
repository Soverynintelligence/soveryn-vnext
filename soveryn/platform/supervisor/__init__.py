"""Supervision boundary for health checks and autonomy budgets.

This package describes systemd-facing health policy and the constraints that
keep repair actions bounded. Phase 1 declares shapes only.
"""

from soveryn.platform.supervisor.health import (
    HealthCheck,
    HealthCheckResult,
    HealthProbe,
    HealthState,
)

__all__ = [
    "HealthCheck",
    "HealthCheckResult",
    "HealthProbe",
    "HealthState",
]
