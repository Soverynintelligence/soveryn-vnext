"""Tests for the readiness wait loop used by systemd ExecStartPre."""

from __future__ import annotations

from soveryn.platform.supervisor.health import HealthCheck, HealthCheckResult
from soveryn.platform.supervisor.readiness import parse_args, wait_for_health


class _ScriptedProbe:
    """Returns a scripted sequence of HealthCheckResults across successive checks."""

    def __init__(self, results: list[HealthCheckResult]):
        self._results = list(results)
        self.calls: list[HealthCheck] = []

    def check(self, check: HealthCheck) -> HealthCheckResult:
        self.calls.append(check)
        if not self._results:
            return HealthCheckResult(check.name, "unknown", "scripted probe exhausted")
        return self._results.pop(0)


def test_wait_returns_true_on_first_ok():
    probe = _ScriptedProbe([HealthCheckResult("router", "ok", "HTTP 200")])
    check = HealthCheck(name="router", target="http://127.0.0.1:8090/props")
    ok = wait_for_health(check, max_wait_seconds=5.0, poll_interval_seconds=0.1, probe=probe, sleep=lambda s: None, now=lambda: 0.0)
    assert ok is True
    assert len(probe.calls) == 1


def test_wait_returns_true_after_n_unknowns():
    probe = _ScriptedProbe([
        HealthCheckResult("router", "unknown", "starting"),
        HealthCheckResult("router", "unknown", "starting"),
        HealthCheckResult("router", "ok", "HTTP 200"),
    ])
    clock = {"now": 0.0}

    def now() -> float:
        return clock["now"]

    def sleep(seconds: float) -> None:
        clock["now"] += seconds

    check = HealthCheck(name="router", target="http://127.0.0.1:8090/props")
    ok = wait_for_health(check, max_wait_seconds=5.0, poll_interval_seconds=0.1, probe=probe, sleep=sleep, now=now)
    assert ok is True
    assert len(probe.calls) == 3


def test_wait_returns_false_on_timeout():
    probe = _ScriptedProbe([HealthCheckResult("x", "unknown", "")])
    clock = {"now": 0.0}
    sleeps: list[float] = []

    def now() -> float:
        return clock["now"]

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock["now"] += seconds

    check = HealthCheck(name="x", target="http://nowhere.invalid")
    ok = wait_for_health(check, max_wait_seconds=1.0, poll_interval_seconds=0.25, probe=probe, sleep=sleep, now=now)
    assert ok is False
    assert sum(sleeps) == 1.0


def test_wait_returns_false_on_fail_state():
    probe = _ScriptedProbe([HealthCheckResult("router", "fail", "HTTP 503")])
    check = HealthCheck(name="router", target="http://127.0.0.1:8090/props")
    sleeps: list[float] = []
    ok = wait_for_health(check, max_wait_seconds=5.0, poll_interval_seconds=0.1, probe=probe, sleep=sleeps.append, now=lambda: 0.0)
    assert ok is False
    assert sleeps == []


def test_cli_parsing_captures_target_and_budgets():
    args = parse_args(["http://127.0.0.1:8090/props", "--max-wait", "12.5", "--poll-interval", "0.5", "--name", "router"])
    assert args.target == "http://127.0.0.1:8090/props"
    assert args.max_wait_seconds == 12.5
    assert args.poll_interval_seconds == 0.5
    assert args.name == "router"
