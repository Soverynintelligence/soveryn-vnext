"""Probe declared surfaces. Three outcomes, and UNKNOWN is one of them.

The whole point of this module is the third state.

Every failure this week collapsed "I could not check" into "nothing is wrong":

  * `recent_self_audit` queried four stores, found nothing, and reported an
    empty audit — while the dispatch sat in a fifth store it never opened.
  * Ares's GPU lane returned `[]` when nvidia-smi exited non-zero, and the
    tracker read three healthy cards.
  * `systemctl is-active` said the Telegram bridge was active for eight days
    while it delivered nothing.

So `Status` has three members and the code is never allowed to fold UNKNOWN into
HEALTHY. A caller that wants to treat them the same must say so itself.
"""
from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import Enum

from soveryn.platform.surfaces.registry import Kind, Surface


class Status(str, Enum):
    HEALTHY = "healthy"
    FAILED = "failed"      # probed, and it is wrong
    UNKNOWN = "unknown"    # could not probe — NOT an all-clear


@dataclass(frozen=True)
class Result:
    surface: str
    status: Status
    detail: str
    latency_s: float
    checked_at: float

    @property
    def ok(self) -> bool:
        """True only for HEALTHY. UNKNOWN is not ok — that is the point."""
        return self.status is Status.HEALTHY


# Cloudflare returns 403 to `Python-urllib/3.x`. The first run of this probe
# reported five healthy public sites as DOWN for exactly that reason. A monitor
# that cries wolf gets muted, and a muted monitor is how Ares ended up holding
# 53 lint findings that nobody read while real outages ran underneath. Identify
# honestly as a health check rather than impersonating a browser.
_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/120.0 Safari/537.36 SOVERYN-surface-probe/1.0")


def _http(surface: Surface, timeout: float) -> Result:
    t0 = time.monotonic()
    headers = {"User-Agent": _UA, "Accept": "*/*"}
    if surface.payload:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        surface.target,
        method=surface.method,
        data=json.dumps(surface.payload).encode() if surface.payload else None,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            code, body = r.status, r.read(65536).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        # An HTTP error IS a probe result — we reached it and it answered.
        # Shepherd's healthy answer is 401; treating every non-2xx as an outage
        # would report a working auth gate as down.
        code, body = exc.code, ""
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return Result(surface.name, Status.UNKNOWN,
                      f"could not reach: {type(exc).__name__}: {exc}",
                      time.monotonic() - t0, time.time())
    el = time.monotonic() - t0

    if code != surface.expect_status:
        return Result(surface.name, Status.FAILED,
                      f"HTTP {code}, expected {surface.expect_status}", el, time.time())
    if surface.expect_contains and surface.expect_contains.lower() not in body.lower():
        return Result(surface.name, Status.FAILED,
                      f"HTTP {code} but response lacks {surface.expect_contains!r} "
                      f"— answering, not working", el, time.time())

    if surface.expect_json_field:
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return Result(surface.name, Status.FAILED,
                          f"HTTP {code} but body is not JSON", el, time.time())
        value = data.get(surface.expect_json_field)
        if not isinstance(value, str) or not value.strip():
            return Result(surface.name, Status.FAILED,
                          f"HTTP {code} but {surface.expect_json_field!r} is "
                          f"missing or empty — answering, not working",
                          el, time.time())
        if len(value.strip()) < surface.expect_min_chars:
            return Result(surface.name, Status.FAILED,
                          f"HTTP {code} but {surface.expect_json_field!r} is only "
                          f"{len(value.strip())} chars, expected >= "
                          f"{surface.expect_min_chars}", el, time.time())

    return Result(surface.name, Status.HEALTHY, f"HTTP {code}", el, time.time())


def _unit(surface: Surface, timeout: float) -> Result:
    t0 = time.monotonic()
    try:
        r = subprocess.run(["systemctl", "--user", "is-active", surface.target],
                           capture_output=True, text=True, timeout=timeout)
    except Exception as exc:
        return Result(surface.name, Status.UNKNOWN,
                      f"systemctl failed: {type(exc).__name__}: {exc}",
                      time.monotonic() - t0, time.time())
    el = time.monotonic() - t0
    state = r.stdout.strip()
    if state == "active":
        return Result(surface.name, Status.HEALTHY, "active", el, time.time())
    if not state:
        return Result(surface.name, Status.UNKNOWN, "systemctl returned nothing",
                      el, time.time())
    return Result(surface.name, Status.FAILED, f"unit is {state}", el, time.time())


def probe(surface: Surface, *, timeout: float = 20.0) -> Result:
    if surface.retired:
        return Result(surface.name, Status.HEALTHY,
                      f"retired: {surface.retired[:60]}", 0.0, time.time())
    if surface.kind is Kind.UNIT:
        return _unit(surface, timeout)
    return _http(surface, timeout)


def probe_all(surfaces, *, timeout: float = 20.0) -> list[Result]:
    return [probe(s, timeout=timeout) for s in surfaces]
