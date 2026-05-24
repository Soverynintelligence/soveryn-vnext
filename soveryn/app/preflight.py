"""SOVERYN vNext — startup preflight.

Runs the static config invariants (already enforced at import in
soveryn.config.runtime._validate) AND the network/process health checks
in soveryn.inference.health. Returns a PreflightReport — does NOT call
sys.exit (per Jon constraint 5). The CLI wrapper at the bottom of this
module is the only thing that exits nonzero on failure.
"""

from __future__ import annotations
import sys
from dataclasses import dataclass, field

from soveryn.config import runtime
from soveryn.config.loader import EnvConfig, load_env_config
from soveryn.inference.health import (
    DEFAULT_TIMEOUT_SECONDS,
    HealthResult,
    check_llama_server,
    check_runtime_service,
    check_service_endpoint,
)


@dataclass(frozen=True)
class PreflightReport:
    """Result of a preflight run. `ok` is the AND of every check.

    `deferred` results (in-process threads we can't check yet) do NOT
    count as failures — they're explicitly out of scope at preflight time.
    """
    env: EnvConfig
    results: tuple[HealthResult, ...]

    @property
    def ok(self) -> bool:
        return all(r.status != "fail" for r in self.results)

    @property
    def failures(self) -> tuple[HealthResult, ...]:
        return tuple(r for r in self.results if r.status == "fail")

    def format_text(self) -> str:
        """Human-readable report — one line per check, summary at end."""
        lines = []
        lines.append(f"SOVERYN vNext preflight — app_port={self.env.app_port}, "
                     f"health_timeout={self.env.health_timeout_seconds}s")
        lines.append("")
        for r in self.results:
            mark = {"ok": "✓", "fail": "✗", "deferred": "·"}[r.status]
            lines.append(f"  {mark} [{r.kind}] {r.name:<24} {r.latency_ms:>6.1f}ms  {r.detail}")
        lines.append("")
        if self.ok:
            lines.append(f"PREFLIGHT OK ({len(self.results)} checks, "
                         f"{sum(r.status == 'deferred' for r in self.results)} deferred)")
        else:
            lines.append(f"PREFLIGHT FAILED — {len(self.failures)} failure(s):")
            for f in self.failures:
                lines.append(f"  - {f.name}: {f.detail}")
        return "\n".join(lines)


def run_preflight(
    env: EnvConfig | None = None,
    timeout: float | None = None,
) -> PreflightReport:
    """Run all health checks and return a report.

    Does NOT exit. The library-level contract is pure: env in, report out.
    Static config invariants (no retired-name leaks, no port collisions)
    were already enforced at import time by soveryn.config.runtime._validate.
    """
    env = env if env is not None else load_env_config()
    t = timeout if timeout is not None else env.health_timeout_seconds

    results: list[HealthResult] = []
    for server in runtime.MODEL_SERVERS:
        results.append(check_llama_server(server, timeout=t))
    for endpoint in runtime.SERVICE_ENDPOINTS:
        results.append(check_service_endpoint(endpoint, timeout=t))
    for service in runtime.RUNTIME_SERVICES:
        results.append(check_runtime_service(service, timeout=t))

    return PreflightReport(env=env, results=tuple(results))


def _cli() -> int:
    """CLI entrypoint: print report, return exit code."""
    report = run_preflight()
    print(report.format_text())
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(_cli())
