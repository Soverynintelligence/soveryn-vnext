"""Production wiring for the deep cognition cycle.

`CognitionDaemon` has existed, fully tested, since 2026-06-22 and has never run
a single cycle. Twelve test files, a testable decision core, a `CognitionStore`
wired into app startup and read correctly by Mission Control — and no caller.
The UI reported "the cognition engine hasn't run" and was telling the truth.

`RUNTIME_SERVICES` declared it as a thread started inside app.py. No such thread
was ever written. This module supplies what was actually missing: the four
injected dependencies, resolved against real infrastructure, behind an
entry point that systemd can start — the same shape as dream, heartbeat and
representation, all of which run as their own user units.

## Gated off by default

`SOVERYN_COGNITION_CYCLE_ENABLED` defaults to false. Starting a reflection loop
against a live fleet is a behaviour change, not a bug fix, and it should be an
explicit decision. `SOVERYN_COGNITION_CYCLE_DRY_RUN=true` runs the gate and logs
whether a cycle *would* have fired without calling a model or writing a note —
which is the cheap way to answer the open question below.

## The open question this is designed to answer

The daemon fires only when the system has been idle for `idle_threshold_seconds`
AND `tick_interval_seconds` have passed since the last cycle. On a box running a
30-minute heartbeat, patrols, dream cycles and Ares, genuine idle may be rarer
than the 5-minute default assumes. If `last_activity_fn` never goes quiet, the
gate is permanently shut and wiring alone changes nothing. Run dry for a day
first; the log will say plainly whether it would ever have fired.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from soveryn.agents.cognition.daemon import CognitionDaemon, CognitionDaemonConfig
from soveryn.agents.cognition.store import CognitionStore
from soveryn.agents.cognition.types import Turn
from soveryn.agents.dream.cognition import chat_completion

logger = logging.getLogger(__name__)

DEFAULT_COGNITION_URL = "http://127.0.0.1:8089"
DEFAULT_TICK_SECONDS = 1800.0      # 30 min — no faster than the heartbeat
DEFAULT_IDLE_SECONDS = 900.0       # 15 min — a real lull, not a typing pause
DEFAULT_POLL_SECONDS = 300.0       # check the gate every 5 min, run at most per tick
# Must comfortably exceed the idle threshold. The cycle only runs when the box
# has been QUIET, so a lookback anchored near the idle window is self-defeating:
# at 03:50 on 2026-08-03 it fired correctly and got turns=0, because "recent
# activity" and "system is idle" exclude each other on a single-user machine.
# 48h lets a 4am cycle reflect on yesterday evening.
DEFAULT_TURN_LOOKBACK_HOURS = 48
DEFAULT_MAX_TURNS = 40
DEFAULT_TIMEOUT_SECONDS = 180


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    return default if raw is None else raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


def make_chat_fn(url: str, timeout: int = DEFAULT_TIMEOUT_SECONDS):
    """Adapt the cognition surface to the daemon's ChatFn(system, user) -> str."""
    def _chat(system: str, user: str) -> str:
        return chat_completion(
            url=url,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            timeout=timeout,
        )
    return _chat


def make_conversation_sources(conv_store, agent: str, *, now_fn=None):
    """Return (last_activity_fn, recent_turns_fn) backed by the conversation store.

    `last_activity_fn` must return a MONOTONIC timestamp, because the daemon
    compares it against `now_fn()` which defaults to time.monotonic. Wall-clock
    rows therefore have to be converted, not returned raw — mixing the two clocks
    silently produces a gate that either never opens or always does.
    """
    monotonic = now_fn or time.monotonic

    def last_activity_fn() -> float:
        since = datetime.now(timezone.utc) - timedelta(hours=DEFAULT_TURN_LOOKBACK_HOURS)
        try:
            sessions = conv_store.list_sessions_with_recent_activity(
                agent=agent, since=since, exclude_session_id="",
            )
        except Exception:  # store unavailable — treat as "busy", never as idle
            logger.exception("cognition: conversation store unreadable")
            return monotonic()
        if not sessions:
            # No activity in the lookback window: genuinely idle. Report a
            # timestamp far enough back that the idle gate opens.
            return monotonic() - DEFAULT_TURN_LOOKBACK_HOURS * 3600.0
        # Session.updated_at is an ISO string in NAIVE LOCAL time, not UTC and
        # not a datetime. Comparing it against an aware UTC now() silently skews
        # the gate by the UTC offset — the same defect that broke _age() in the
        # delegation surface. Parse naive, compare naive.
        stamps = []
        for s in sessions:
            raw = getattr(s, "updated_at", None) or getattr(s, "created_at", None)
            if not raw:
                continue
            try:
                stamps.append(datetime.fromisoformat(str(raw)))
            except ValueError:
                logger.warning("cognition: unparseable session timestamp %r", raw)
        if not stamps:
            return monotonic()
        newest = max(stamps)
        if newest.tzinfo is not None:
            newest = newest.astimezone().replace(tzinfo=None)
        age = (datetime.now() - newest).total_seconds()
        return monotonic() - max(0.0, age)

    def recent_turns_fn() -> list[Turn]:
        since = datetime.now(timezone.utc) - timedelta(hours=DEFAULT_TURN_LOOKBACK_HOURS)
        try:
            sessions = conv_store.list_sessions_with_recent_activity(
                agent=agent, since=since, exclude_session_id="",
            )
        except Exception:
            logger.exception("cognition: conversation store unreadable")
            return []
        turns: list[Turn] = []
        for s in sessions:
            try:
                turns.extend(conv_store.load_history(s.session_id))
            except Exception:
                logger.warning("cognition: could not load session %s", s.session_id)
        return turns[-DEFAULT_MAX_TURNS:]

    return last_activity_fn, recent_turns_fn


def build_daemon(conv_store, lattice_db: Path, agent: str = "aetheria") -> CognitionDaemon:
    url = os.environ.get("SOVERYN_COGNITION_INSTANCE_URL", DEFAULT_COGNITION_URL)
    chat = make_chat_fn(url)
    last_activity_fn, recent_turns_fn = make_conversation_sources(conv_store, agent)
    return CognitionDaemon(
        CognitionDaemonConfig(
            tick_interval_seconds=_env_float("SOVERYN_COGNITION_TICK_SECONDS",
                                             DEFAULT_TICK_SECONDS),
            idle_threshold_seconds=_env_float("SOVERYN_COGNITION_IDLE_SECONDS",
                                              DEFAULT_IDLE_SECONDS),
            poll_interval_seconds=_env_float("SOVERYN_COGNITION_POLL_SECONDS",
                                             DEFAULT_POLL_SECONDS),
            agent=agent,
        ),
        CognitionStore(lattice_db),
        last_activity_fn=last_activity_fn,
        recent_turns_fn=recent_turns_fn,
        # The cycle docstring notes these may be the same object in production.
        reflect_chat_fn=chat,
        distill_chat_fn=chat,
    )


def _main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not _env_flag("SOVERYN_COGNITION_CYCLE_ENABLED"):
        logger.warning(
            "cognition cycle disabled — set SOVERYN_COGNITION_CYCLE_ENABLED=true. "
            "Exiting without running."
        )
        return 0

    from soveryn.config.loader import load_env_config
    from soveryn.memory.conversation_store import ConversationStore

    env = load_env_config()
    conv_store = ConversationStore(env.conversations_db)
    daemon = build_daemon(conv_store, env.lattice_db)

    if _env_flag("SOVERYN_COGNITION_CYCLE_DRY_RUN", default=True):
        # Evaluate the gate on a loop and report, without calling a model or
        # writing a note. Answers "would this ever fire?" at zero risk.
        logger.info("cognition cycle DRY RUN — gate only, no model calls, no writes")
        while True:
            try:
                now = time.monotonic()
                idle_for = now - daemon._last_activity_fn()
                would_run = daemon.should_run_deep(now)
                logger.info(
                    "cognition gate: would_run=%s  idle_for=%.0fs  "
                    "idle_threshold=%.0fs  tick=%.0fs",
                    would_run, idle_for,
                    daemon.config.idle_threshold_seconds,
                    daemon.config.tick_interval_seconds,
                )
            except Exception:
                logger.exception("cognition gate evaluation failed")
            time.sleep(60)

    # The daemon logs cycle detail at DEBUG and logs nothing when the gate is
    # shut, so at INFO a live run is indistinguishable from a dead one. That is
    # the same write-without-a-read-path defect this whole surface suffered
    # from; do not reintroduce it here. Raise only this package's level, not
    # the root logger — third-party DEBUG would drown the signal.
    logging.getLogger("soveryn.agents.cognition").setLevel(logging.DEBUG)
    logger.info("cognition cycle LIVE — package logging at DEBUG so cycles are visible")
    daemon.run_forever()
    return 0
