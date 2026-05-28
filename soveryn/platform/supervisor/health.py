"""Supervisor health-check probe implementation."""

from __future__ import annotations

import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

HealthState = Literal["ok", "degraded", "fail", "unknown"]


@dataclass(frozen=True)
class HealthCheck:
    """One named health check target.

    Supported target forms:
    - `http://...` or `https://...`: GET probe. 2xx => ok, reachable non-2xx => fail,
      timeout/unreachable => unknown.
    - `file:<path>:<max_age_seconds>`: heartbeat-file probe. Existing fresh file => ok,
      existing stale file => fail, missing/malformed/inaccessible => unknown.
    """

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
    """Pull-based health probe. No status is pushed into supervisor state."""

    def check(self, check: HealthCheck) -> HealthCheckResult:
        target = check.target.strip()
        if target.startswith(("http://", "https://")):
            return self._check_http(check)
        if target.startswith("file:"):
            return self._check_file_heartbeat(check)
        return HealthCheckResult(check.name, "unknown", f"unsupported target {check.target!r}")

    def _check_http(self, check: HealthCheck) -> HealthCheckResult:
        try:
            with urllib.request.urlopen(check.target, timeout=check.timeout_seconds) as resp:
                status = int(resp.status)
                if 200 <= status < 300:
                    return HealthCheckResult(check.name, "ok", f"HTTP {status}")
                return HealthCheckResult(check.name, "fail", f"HTTP {status}")
        except urllib.error.HTTPError as exc:
            return HealthCheckResult(check.name, "fail", f"HTTP {exc.code}")
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            return HealthCheckResult(check.name, "unknown", f"unreachable: {exc}")
        except Exception as exc:
            return HealthCheckResult(check.name, "unknown", f"{type(exc).__name__}: {exc}")

    def _check_file_heartbeat(self, check: HealthCheck) -> HealthCheckResult:
        try:
            _, raw_path, raw_max_age = check.target.split(":", 2)
            max_age_seconds = float(raw_max_age)
        except ValueError:
            return HealthCheckResult(check.name, "unknown", "file target must be file:<path>:<max_age_seconds>")
        except TypeError as exc:
            return HealthCheckResult(check.name, "unknown", f"invalid file target: {exc}")

        path = Path(raw_path)
        try:
            stat = path.stat()
        except FileNotFoundError:
            return HealthCheckResult(check.name, "unknown", f"missing heartbeat file {path}")
        except OSError as exc:
            return HealthCheckResult(check.name, "unknown", f"cannot stat heartbeat file {path}: {exc}")

        age = time.time() - stat.st_mtime
        if age <= max_age_seconds:
            return HealthCheckResult(check.name, "ok", f"heartbeat age {age:.3f}s <= {max_age_seconds:.3f}s")
        return HealthCheckResult(check.name, "fail", f"heartbeat age {age:.3f}s > {max_age_seconds:.3f}s")
