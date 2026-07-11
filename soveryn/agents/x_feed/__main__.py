"""X feed worker launcher — isolated poll loop entrypoint.

Launches `XFeedWorker` as a standalone daemon process, searching X for mentions
and niche terms, scoring tweets, and storing candidates above threshold to
`CandidateStore`. The real Aetheria loop reads this output via `read_x` tool.

Mirrors `soveryn.agents.ares.__main__` in structure: parse_args handles CLI,
build_worker assembles the worker with PresenceConfig.default() and XClient
from environment, and run/main install signal handlers and call run_forever.
"""

from __future__ import annotations

import argparse
import logging
import signal
import time
from dataclasses import dataclass

from soveryn.agents.presence.candidate_store import CandidateStore
from soveryn.agents.presence.config import PresenceConfig
from soveryn.agents.presence.feed_worker import XFeedWorker
from soveryn.agents.presence.x_client import XClient

DEFAULT_INTERVAL_SECONDS = 300.0


@dataclass(slots=True)
class LauncherArgs:
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
        prog="python -m soveryn.agents.x_feed",
        description="SOVERYN X feed worker launcher.",
    )
    parser.add_argument(
        "--interval-seconds",
        type=_positive_float,
        default=DEFAULT_INTERVAL_SECONDS,
        help=f"seconds between polls (default: {DEFAULT_INTERVAL_SECONDS})",
    )
    parser.add_argument(
        "--iterations",
        type=_positive_int,
        default=None,
        help="run N polls and exit (default: run forever)",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> LauncherArgs:
    parsed = _build_parser().parse_args(argv)
    return LauncherArgs(
        interval_seconds=parsed.interval_seconds,
        iterations=parsed.iterations,
    )


def build_worker(args: LauncherArgs) -> XFeedWorker:
    """Assemble an XFeedWorker from default config and environment.

    Reads X API credentials from environment (X_BEARER_TOKEN, X_API_KEY, etc.).
    Uses PresenceConfig.default() for threshold, niche terms, and db paths.
    Uses time.time as the now_fn for deterministic testing.
    """
    cfg = PresenceConfig.default()
    x_client = XClient.from_env()
    store = CandidateStore(cfg.db_path)
    return XFeedWorker(cfg=cfg, x_client=x_client, store=store, now_fn=time.time)


def _install_signal_handlers(shutdown: _ShutdownRequest) -> None:
    signal.signal(signal.SIGTERM, shutdown.request)
    signal.signal(signal.SIGINT, shutdown.request)


def run(
    args: LauncherArgs,
    *,
    worker_factory=build_worker,
    signal_installer=_install_signal_handlers,
) -> int:
    worker = worker_factory(args)
    shutdown = _ShutdownRequest()
    signal_installer(shutdown)
    worker.run_forever(
        interval_seconds=args.interval_seconds,
        iterations=args.iterations,
        stop_requested=shutdown.should_stop,
    )
    return 0


def main(
    argv: list[str] | None = None,
    *,
    worker_factory=build_worker,
    signal_installer=_install_signal_handlers,
) -> int:
    # Configure logging so the poll results and errors reach the service log.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return run(
        parse_args(argv),
        worker_factory=worker_factory,
        signal_installer=signal_installer,
    )


if __name__ == "__main__":
    raise SystemExit(main())
