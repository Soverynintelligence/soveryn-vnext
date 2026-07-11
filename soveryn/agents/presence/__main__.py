"""Presence daemon launcher — mirrors soveryn/agents/ares/__main__.py.

Wires PresenceDaemonSurface (Tasks 1-10) to real infrastructure:
XClient.from_env() for X, an AgentLoop built the same minimal way
soveryn/app/startup.py builds Aetheria's (see build_daemon's docstring for
what's deliberately trimmed), and ares/signal_sender.SignalSender for the
real Signal send. `--dry-run` makes send_fn print instead of sending —
since nothing then reaches Jon over Signal, no approvals can arrive, so a
dry run only exercises ingest -> score -> draft, never publish.

Inbound Signal replies (Jon approving/rejecting/editing a draft) are
handled by soveryn.agents.presence.inbound.handle_inbound_reply, but that
seam is not yet wired to a live inbound source — see inbound.py's
docstring and task-11-report.md.
"""

from __future__ import annotations

import argparse
import logging
import signal
from dataclasses import dataclass
from typing import Callable

from soveryn.agents.ares.signal_sender import SignalSender
from soveryn.agents.loop import AgentLoop
from soveryn.agents.presence.aetheria_bridge import make_draft_fn
from soveryn.agents.presence.candidate_store import CandidateStore
from soveryn.agents.presence.config import PresenceConfig
from soveryn.agents.presence.daemon import PresenceDaemonSurface
from soveryn.agents.presence.signal_log import SignalLog
from soveryn.agents.presence.x_client import XClient
from soveryn.config.loader import load_env_config
from soveryn.memory.conversation_store import ConversationStore

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = 300.0

AETHERIA_AGENT_NAME = "aetheria"


@dataclass(slots=True)
class LauncherArgs:
    dry_run: bool = False
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
        prog="python -m soveryn.agents.presence",
        description="SOVERYN @Soveryn_AI presence daemon launcher.",
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="print Signal messages instead of sending them; no approvals "
             "can arrive, so only ingest/score/draft runs (no publish)",
    )
    parser.set_defaults(dry_run=False)
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


def _dry_run_send_fn(text: str) -> None:
    print(f"[presence dry-run] would send to Signal:\n{text}\n")


def _build_send_fn(sender: SignalSender, *, dry_run: bool) -> Callable[[str], None]:
    if dry_run:
        return _dry_run_send_fn

    def _send(text: str) -> None:
        result = sender.send(text)
        if not result.sent:
            logger.warning("presence Signal send failed: %s", result.reason)

    return _send


def build_daemon(args: LauncherArgs) -> PresenceDaemonSurface:
    """Assemble a real PresenceDaemonSurface.

    Aetheria's AgentLoop is built the same minimal way
    soveryn/app/startup.py's create_app builds it (agent_name, conv_store,
    pinned_text), but WITHOUT startup's tool_registry / lattice recall /
    continuity / coord_store wiring — presence only needs one-shot
    draft-text generation (via aetheria_bridge.make_draft_fn), not
    Aetheria's full tool surface. This is a deliberate trim, not an
    oversight: pulling in create_app's ~800-line build block would couple
    the presence launcher to the entire vnext app wiring (tool registry,
    lattice stores, coordination boards, delegation worker, ...) for a
    capability presence doesn't use. Flagged per the Task 11 brief as a
    concern worth revisiting if presence's drafts ever need recall/tools.
    """
    cfg = PresenceConfig.default()
    x_client = XClient.from_env()
    store = CandidateStore(cfg.db_path)
    signal_log = SignalLog(cfg.signal_log_path)

    env = load_env_config()
    conv_store = ConversationStore(env.conversations_db)
    pinned_text = ""
    if env.pinned_memory_path.is_file():
        pinned_text = env.pinned_memory_path.read_text(encoding="utf-8")
    loop = AgentLoop(AETHERIA_AGENT_NAME, conv_store, pinned_text=pinned_text)
    draft_fn = make_draft_fn(loop, conv_store)

    signal_sender = SignalSender()
    send_fn = _build_send_fn(signal_sender, dry_run=args.dry_run)

    return PresenceDaemonSurface(
        cfg=cfg,
        x_client=x_client,
        store=store,
        draft_fn=draft_fn,
        send_fn=send_fn,
        signal_log=signal_log,
    )


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
