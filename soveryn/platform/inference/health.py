"""SOVERYN vNext — health checks for the runtime fleet.

Stdlib-only probes:
- check_llama_server(server, timeout): HTTP GET /health
- check_kernel_brain(timeout): resolved Kernel brain /health or /v1/models
- check_service_endpoint(endpoint, timeout): TCP connect
- check_runtime_service(service, timeout): conservative process / systemd /
  thread liveness depending on kind

Each returns a HealthResult. NO retries — caller decides if needed.
NO side effects — preflight must not start, stop, or mutate anything
(Jon's constraint 3).
"""

from __future__ import annotations
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from soveryn.config.runtime import ModelServer, RuntimeService, ServiceEndpoint

HealthStatus = Literal["ok", "fail", "deferred"]

DEFAULT_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True)
class HealthResult:
    """Outcome of one health check."""
    name: str               # logical name of the subject
    kind: str               # "model_server" | "service_endpoint" | "runtime_service"
    status: HealthStatus    # "ok" | "fail" | "deferred"
    latency_ms: float       # 0.0 for deferred
    detail: str             # human-readable cause


def _http_ok(url: str, timeout: float) -> tuple[bool, float, str]:
    """GET ``url``. Returns (ok, latency_ms, detail)."""
    started = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            elapsed_ms = (time.monotonic() - started) * 1000.0
            if 200 <= resp.status < 300:
                return True, elapsed_ms, f"HTTP {resp.status} from {url}"
            return False, elapsed_ms, f"HTTP {resp.status} from {url}"
    except urllib.error.URLError as e:
        elapsed_ms = (time.monotonic() - started) * 1000.0
        return False, elapsed_ms, f"URLError: {e.reason} ({url})"
    except (TimeoutError, socket.timeout):
        elapsed_ms = (time.monotonic() - started) * 1000.0
        return False, elapsed_ms, f"timeout after {timeout}s ({url})"
    except Exception as e:
        elapsed_ms = (time.monotonic() - started) * 1000.0
        return False, elapsed_ms, f"{type(e).__name__}: {e} ({url})"


def check_llama_server(server: ModelServer, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> HealthResult:
    """HTTP GET http://<host>:<port>/health — llama-server exposes this."""
    url = f"{server.base_url}/health"
    started = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            elapsed_ms = (time.monotonic() - started) * 1000.0
            if 200 <= resp.status < 300:
                return HealthResult(server.name, "model_server", "ok", elapsed_ms,
                                    f"HTTP {resp.status}")
            return HealthResult(server.name, "model_server", "fail", elapsed_ms,
                                f"HTTP {resp.status}")
    except urllib.error.URLError as e:
        elapsed_ms = (time.monotonic() - started) * 1000.0
        return HealthResult(server.name, "model_server", "fail", elapsed_ms,
                            f"URLError: {e.reason}")
    except (TimeoutError, socket.timeout):
        elapsed_ms = (time.monotonic() - started) * 1000.0
        return HealthResult(server.name, "model_server", "fail", elapsed_ms,
                            f"timeout after {timeout}s")
    except Exception as e:
        elapsed_ms = (time.monotonic() - started) * 1000.0
        return HealthResult(server.name, "model_server", "fail", elapsed_ms,
                            f"{type(e).__name__}: {e}")


def check_kernel_brain(timeout: float = DEFAULT_TIMEOUT_SECONDS) -> HealthResult:
    """Probe the resolved Kernel build brain — never a hardcoded or guessed port.

    Hits ``/health`` first, then ``/v1/models``. Host/port come only from
    ``_kernel_server()`` (``~/.soveryn/kernel_brain`` / ``SOVERYN_KERNEL_BRAIN``).
    """
    from soveryn.config.runtime import _kernel_server, resolve_kernel_brain

    server = _kernel_server()
    key = resolve_kernel_brain()
    last_detail = "no probe attempted"
    last_ms = 0.0
    for path in ("/health", "/v1/models"):
        url = f"{server.base_url}{path}"
        ok, elapsed_ms, detail = _http_ok(url, timeout)
        last_detail, last_ms = detail, elapsed_ms
        if ok:
            return HealthResult(
                "kernel_build",
                "model_server",
                "ok",
                elapsed_ms,
                f"{key} {detail}",
            )
    return HealthResult(
        "kernel_build",
        "model_server",
        "fail",
        last_ms,
        f"{key} {server.base_url} {last_detail}",
    )


def kernel_brain_health_report(timeout: float = DEFAULT_TIMEOUT_SECONDS) -> dict:
    """Verified Kernel-brain probe plus the resolved endpoint record."""
    from soveryn.config.runtime import describe_kernel_brain

    rec = describe_kernel_brain()
    result = check_kernel_brain(timeout=timeout)
    probed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    target = rec["base_url"]
    probe = {
        "target": target,
        "timestamp": probed_at,
        "result": result.status,
        "name": result.name,
        "detail": result.detail,
    }
    return {
        **rec,
        "status": result.status,
        "detail": result.detail,
        "latency_ms": result.latency_ms,
        "probed": True,
        "probed_at": probed_at,
        "target": target,
        "probe": probe,
    }


def format_kernel_brain_health_block(
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    *,
    report: dict | None = None,
) -> str:
    """Prompt block: real endpoint + verified probe. Do not invent ports."""
    report = report if report is not None else kernel_brain_health_report(timeout=timeout)
    probe = report.get("probe") if isinstance(report.get("probe"), dict) else {}
    target = probe.get("target") or report.get("base_url")
    timestamp = probe.get("timestamp") or report.get("probed_at") or ""
    result = probe.get("result") or report.get("status")
    return (
        "## Kernel build brain (verified probe — do not invent an endpoint)\n"
        f"Active brain: `{report['brain']}` ({report['alias']}) at "
        f"{report['base_url']}.\n"
        f"Probe: {report['detail']} → {report['status']}.\n"
        f"Probe record: target={target} timestamp={timestamp} result={result}.\n"
        "Never claim this brain is down at a guessed port "
        "(including 127.0.0.1:8080). Only this probe result is allowed.\n"
        "A down or blocked claim without a matching same-run probe record "
        "is unverified and must not block dispatch.\n\n"
    )


def check_service_endpoint(endpoint: ServiceEndpoint, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> HealthResult:
    """TCP-connect probe — service-agnostic, just confirms something is listening."""
    started = time.monotonic()
    try:
        with socket.create_connection(("127.0.0.1", endpoint.port), timeout=timeout):
            elapsed_ms = (time.monotonic() - started) * 1000.0
            return HealthResult(endpoint.name, "service_endpoint", "ok", elapsed_ms,
                                f"TCP connect to :{endpoint.port}")
    except (socket.timeout, TimeoutError):
        elapsed_ms = (time.monotonic() - started) * 1000.0
        return HealthResult(endpoint.name, "service_endpoint", "fail", elapsed_ms,
                            f"timeout after {timeout}s")
    except (ConnectionRefusedError, OSError) as e:
        elapsed_ms = (time.monotonic() - started) * 1000.0
        return HealthResult(endpoint.name, "service_endpoint", "fail", elapsed_ms,
                            f"{type(e).__name__}: {e}")


def check_runtime_service(service: RuntimeService, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> HealthResult:
    """Conservative liveness check.

    Per Jon constraint 7: keep specifics small and testable. We dispatch by
    `kind` and use the most boring tool that works:
      - process:   `pgrep -af <name>` — alive if any match
      - scheduled: `systemctl --user is-active <name>.timer` (then system-wide)
      - thread:    DEFERRED — preflight can't check in-app threads (they
                   don't exist yet at preflight time)

    Subprocess calls are timeout-bounded so a hung system call can't stall
    preflight.
    """
    if service.kind == "thread":
        return HealthResult(service.name, "runtime_service", "deferred", 0.0,
                            "in-process thread — check at app runtime")

    if service.kind == "process":
        return _check_process(service.name, timeout)

    if service.kind == "scheduled":
        return _check_scheduled(service.name, timeout)

    return HealthResult(service.name, "runtime_service", "fail", 0.0,
                        f"unknown kind {service.kind!r}")


def _check_process(name: str, timeout: float) -> HealthResult:
    """`pgrep -af <name>` — conservative; any match counts as alive."""
    started = time.monotonic()
    try:
        result = subprocess.run(
            ["pgrep", "-af", name],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
        elapsed_ms = (time.monotonic() - started) * 1000.0
        if result.returncode == 0 and result.stdout.strip():
            line_count = len(result.stdout.strip().splitlines())
            return HealthResult(name, "runtime_service", "ok", elapsed_ms,
                                f"{line_count} matching process(es)")
        return HealthResult(name, "runtime_service", "fail", elapsed_ms,
                            "no matching process")
    except subprocess.TimeoutExpired:
        return HealthResult(name, "runtime_service", "fail",
                            (time.monotonic() - started) * 1000.0,
                            f"pgrep timeout after {timeout}s")
    except FileNotFoundError:
        return HealthResult(name, "runtime_service", "fail",
                            (time.monotonic() - started) * 1000.0,
                            "pgrep not installed")


def _check_scheduled(name: str, timeout: float) -> HealthResult:
    """`systemctl --user is-active <name>.timer`, fall back to system-wide."""
    started = time.monotonic()
    # Normalize underscores → dashes; build candidate unit names.
    candidates = [
        f"soveryn-{name.replace('_', '-')}.timer",
        f"{name.replace('_', '-')}.timer",
    ]
    for candidate in candidates:
        for scope in ("--user", "--system"):
            try:
                result = subprocess.run(
                    ["systemctl", scope, "is-active", candidate],
                    capture_output=True, text=True, timeout=timeout, check=False,
                )
                if result.returncode == 0:
                    elapsed_ms = (time.monotonic() - started) * 1000.0
                    return HealthResult(name, "runtime_service", "ok", elapsed_ms,
                                        f"{scope.lstrip('-')} {candidate}: active")
            except subprocess.TimeoutExpired:
                continue
            except FileNotFoundError:
                return HealthResult(name, "runtime_service", "fail",
                                    (time.monotonic() - started) * 1000.0,
                                    "systemctl not installed")
    elapsed_ms = (time.monotonic() - started) * 1000.0
    return HealthResult(name, "runtime_service", "fail", elapsed_ms,
                        f"no active timer matching {candidates}")
