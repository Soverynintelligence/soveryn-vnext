"""Readiness wait loop for systemd ExecStartPre."""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from typing import Callable

from soveryn.platform.supervisor.health import HealthCheck, HealthProbe


@dataclass(frozen=True)
class ReadinessArgs:
    target: str
    max_wait_seconds: float
    poll_interval_seconds: float
    name: str = "readiness"


def _positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected a positive float, got {value!r}") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError(f"expected a positive float, got {value!r}")
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m soveryn.platform.supervisor.readiness",
        description="Poll a HealthProbe target until it is ready or times out.",
    )
    parser.add_argument("target", help="HealthCheck target (http://..., https://..., or file:...)")
    parser.add_argument("--name", default="readiness", help="logical check name (default: readiness)")
    parser.add_argument("--max-wait", type=_positive_float, required=True, help="maximum wait budget in seconds")
    parser.add_argument(
        "--poll-interval",
        type=_positive_float,
        default=1.0,
        help="seconds to sleep between unsuccessful polls (default: 1.0)",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> ReadinessArgs:
    parsed = _build_parser().parse_args(argv)
    return ReadinessArgs(
        target=parsed.target,
        max_wait_seconds=parsed.max_wait,
        poll_interval_seconds=parsed.poll_interval,
        name=parsed.name,
    )


def wait_for_health(
    check: HealthCheck,
    *,
    max_wait_seconds: float,
    poll_interval_seconds: float = 1.0,
    probe: HealthProbe | None = None,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
) -> bool:
    probe = probe or HealthProbe()
    start = now()
    deadline = start + max_wait_seconds
    while True:
        result = probe.check(check)
        if result.state == "ok":
            return True
        if result.state == "fail":
            return False
        remaining = deadline - now()
        if remaining <= 0:
            return False
        sleep(min(poll_interval_seconds, remaining))


def run(argv: list[str] | None = None, *, probe: HealthProbe | None = None) -> int:
    args = parse_args(argv)
    ok = wait_for_health(
        HealthCheck(args.name, args.target),
        max_wait_seconds=args.max_wait_seconds,
        poll_interval_seconds=args.poll_interval_seconds,
        probe=probe,
    )
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
