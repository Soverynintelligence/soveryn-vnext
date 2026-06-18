"""Ares daemon launcher."""

from __future__ import annotations

import argparse
import logging
import signal
from dataclasses import dataclass

from soveryn.agents.ares.daemon import AresDaemonSurface

DEFAULT_INTERVAL_SECONDS = 60.0


@dataclass(slots=True)
class LauncherArgs:
    dry_run: bool = True
    interval_seconds: float = DEFAULT_INTERVAL_SECONDS
    iterations: int | None = None


@dataclass(slots=True)
class _ShutdownRequest:
    requested: bool = False

    def request(self, signum: int | None = None, frame: object | None = None) -> None:
        self.requested = True

    def should_stop(self) -> bool:
        return self.requested


def _positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected a positive float, got {value!r}") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError(f"expected a positive float, got {value!r}")
    return parsed


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected a positive int, got {value!r}") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError(f"expected a positive int, got {value!r}")
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m soveryn.agents.ares",
        description="SOVERYN Ares daemon launcher.",
    )
    parser.add_argument(
        "--no-dry-run",
        dest="dry_run",
        action="store_false",
        help="enable Signal alerting instead of dry-run telemetry only",
    )
    parser.set_defaults(dry_run=True)
    parser.add_argument(
        "--interval-seconds",
        type=_positive_float,
        default=DEFAULT_INTERVAL_SECONDS,
        help=f"seconds between scans (default: {DEFAULT_INTERVAL_SECONDS})",
    )
    parser.add_argument(
        "--iterations",
        type=_positive_int,
        default=None,
        help="run N scans and exit (default: run forever)",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> LauncherArgs:
    parsed = _build_parser().parse_args(argv)
    return LauncherArgs(
        dry_run=parsed.dry_run,
        interval_seconds=parsed.interval_seconds,
        iterations=parsed.iterations,
    )


def build_daemon(args: LauncherArgs) -> AresDaemonSurface:
    return AresDaemonSurface(dry_run=args.dry_run)


def _install_signal_handlers(shutdown: _ShutdownRequest) -> None:
    signal.signal(signal.SIGTERM, shutdown.request)
    signal.signal(signal.SIGINT, shutdown.request)


def run(
    args: LauncherArgs,
    *,
    daemon_factory=build_daemon,
    signal_installer=_install_signal_handlers,
) -> int:
    daemon = daemon_factory(args)
    shutdown = _ShutdownRequest()
    signal_installer(shutdown)
    daemon.run_forever(
        interval_seconds=args.interval_seconds,
        iterations=args.iterations,
        stop_requested=shutdown.should_stop,
    )
    return 0


def main(
    argv: list[str] | None = None,
    *,
    daemon_factory=build_daemon,
    signal_installer=_install_signal_handlers,
) -> int:
    # Configure logging so the audit trail (finding transitions) reaches the
    # service log. Without this Ares ran for days with an empty log.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return run(
        parse_args(argv),
        daemon_factory=daemon_factory,
        signal_installer=signal_installer,
    )


if __name__ == "__main__":
    raise SystemExit(main())
