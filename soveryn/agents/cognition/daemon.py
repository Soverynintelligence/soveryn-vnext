"""Cognition daemon — quiet-time scheduler for the deep cognition cycle.

Spec: docs/superpowers/specs/2026-06-22-continuous-cognition-design.md
      Phase 2, Task 2.4b — deep-tier cognition daemon (scheduler).

## What this module does

`CognitionDaemon` wraps `run_deep_cycle()` with a quiet-time / idle gate so
the cycle only fires when:

  (a) The system is idle — i.e. `now − last_activity ≥ idle_threshold_seconds`
  (b) Enough time has passed since the last deep cycle — i.e.
      `now − last_cycle_at ≥ tick_interval_seconds` (or never run)

This mirrors the dream daemon's shape: a config dataclass, dependency-injected
clock + data sources, a testable decision core (`should_run_deep`), a thin
`maybe_run_deep_cycle()` that does one guarded pass, and a minimal
`run_forever()` loop.

## Dependency injection

All external dependencies are injected so the daemon is fully testable
without real clocks, real models, or a real conversation store:

  now_fn()            → float   injected clock (default: time.monotonic)
  last_activity_fn()  → float   timestamp of last user activity
  recent_turns_fn()   → list[Turn]   recent conversation turns to reflect on
  reflect_chat_fn     → ChatFn  injected model for reflection pass
  distill_chat_fn     → ChatFn  injected model for distillation pass

In production these are wired to the real conversation store and real model
endpoints.  In tests they are replaced with fakes.

## What this module does NOT do

No heartbeat, no DB writes beyond delegating to run_deep_cycle / CognitionStore.
The `run_forever()` loop is kept minimal and is NOT unit-tested (it's an
infinite sleep loop with a stop flag, identical in shape to the dream daemon).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable

from soveryn.agents.cognition.cycle import CycleResult, run_deep_cycle
from soveryn.agents.cognition.store import CognitionStore
from soveryn.agents.cognition.types import Turn


logger = logging.getLogger(__name__)

# ─── Type alias ───────────────────────────────────────────────────────────────

ChatFn = Callable[[str, str], str]
"""chat_fn(system: str, user: str) -> str — injected inference callable."""


# ─── Config ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CognitionDaemonConfig:
    """Immutable config for the cognition daemon.

    tick_interval_seconds:
        Minimum time between deep cycles (backoff gate).  Even if the system
        is idle, the daemon will not re-run until this interval has elapsed
        since the last cycle.

    idle_threshold_seconds:
        Minimum idle time before a cycle is allowed.  Idle is defined as
        (now − last_activity) >= idle_threshold_seconds.

    agent:
        Agent name forwarded to run_deep_cycle ("aetheria", "vett", …).
    """

    tick_interval_seconds: float = 600.0   # 10 minutes default
    idle_threshold_seconds: float = 300.0  # 5 minutes default
    agent: str = "aetheria"


# ─── Daemon ───────────────────────────────────────────────────────────────────

class CognitionDaemon:
    """Quiet-time scheduler for the deep cognition cycle.

    Wraps run_deep_cycle() so it only fires when the system is idle AND
    enough time has passed since the last cycle.  All external dependencies
    are injected — no real clock, no real model, no real conversation source
    needed for testing.

    Parameters
    ----------
    config : CognitionDaemonConfig
        Intervals, thresholds, agent name.

    store : CognitionStore
        The cognition store to read from and write to.  Shared with
        run_deep_cycle.

    now_fn : () -> float
        Clock injection.  Returns a monotonic timestamp.  Defaults to
        time.monotonic in production.

    last_activity_fn : () -> float
        Returns the monotonic timestamp of the most recent user activity.
        Production wires this to the conversation store.

    recent_turns_fn : () -> list[Turn]
        Returns recent conversation turns to pass into the cycle.
        Production wires this to the conversation store.

    reflect_chat_fn : ChatFn
        Injected inference callable for the reflection pass.

    distill_chat_fn : ChatFn
        Injected inference callable for the distillation pass.
    """

    def __init__(
        self,
        config: CognitionDaemonConfig,
        store: CognitionStore,
        *,
        now_fn: Callable[[], float] | None = None,
        last_activity_fn: Callable[[], float],
        recent_turns_fn: Callable[[], list[Turn]],
        reflect_chat_fn: ChatFn,
        distill_chat_fn: ChatFn,
    ) -> None:
        self.config = config
        self.store = store
        self._now_fn: Callable[[], float] = now_fn if now_fn is not None else time.monotonic
        self._last_activity_fn = last_activity_fn
        self._recent_turns_fn = recent_turns_fn
        self._reflect_chat_fn = reflect_chat_fn
        self._distill_chat_fn = distill_chat_fn

        # Mutable state: tracks when the last deep cycle completed.
        # None means the daemon has never run a cycle yet.
        self._last_cycle_at: float | None = None

        self._stop = False

    # ─── Decision core (pure — no side effects) ───────────────────────────────

    def should_run_deep(self, now: float) -> bool:
        """Pure gate — true only when BOTH quiet-time conditions are met.

        Condition (a): idle ≥ idle_threshold
            (now − last_activity) >= config.idle_threshold_seconds

        Condition (b): enough time since last cycle
            _last_cycle_at is None (never run)
            OR (now − _last_cycle_at) >= config.tick_interval_seconds

        No timers, no side effects.  Takes `now` so tests can inject a fake
        clock value directly without touching now_fn.
        """
        # Gate (a): idle check
        last_activity = self._last_activity_fn()
        idle_seconds = now - last_activity
        if idle_seconds < self.config.idle_threshold_seconds:
            return False

        # Gate (b): backoff since last cycle
        if self._last_cycle_at is not None:
            elapsed = now - self._last_cycle_at
            if elapsed < self.config.tick_interval_seconds:
                return False

        return True

    # ─── Guarded cycle ────────────────────────────────────────────────────────

    def maybe_run_deep_cycle(self) -> CycleResult | None:
        """Run a deep cycle if quiet-time conditions hold; else return None.

        If should_run_deep() is true:
          1. Gather recent_turns_fn()
          2. Call run_deep_cycle(...)
          3. Record _last_cycle_at so the tick_interval gate blocks re-entry
          4. Return the CycleResult

        If should_run_deep() is false, return None without touching the model.
        """
        now = self._now_fn()
        if not self.should_run_deep(now):
            return None

        turns = self._recent_turns_fn()
        logger.debug(
            "cognition daemon: running deep cycle — agent=%s turns=%d",
            self.config.agent, len(turns),
        )

        result = run_deep_cycle(
            agent=self.config.agent,
            turns=turns,
            store=self.store,
            reflect_chat_fn=self._reflect_chat_fn,
            distill_chat_fn=self._distill_chat_fn,
        )

        self._last_cycle_at = now
        logger.info(
            "cognition daemon: cycle complete — candidates=%d integrated=%d note=%s",
            result.candidate_count,
            len(result.process.integrated),
            "written" if result.note is not None else "none",
        )
        return result

    # ─── Thin run loop (not unit-tested — infinite sleep loop) ────────────────

    def run_forever(self) -> None:
        """Spin-bug-resistant tick loop.  Mirrors dream daemon shape.

        Sleeps tick_interval_seconds between checks.  Call daemon._stop = True
        to request a clean shutdown.  SIGTERM / SIGINT handling is left to the
        caller (launch script / systemd unit).
        """
        logger.info(
            "cognition daemon starting. agent=%s tick_interval=%.0fs idle_threshold=%.0fs",
            self.config.agent,
            self.config.tick_interval_seconds,
            self.config.idle_threshold_seconds,
        )
        last_tick_at: float | None = None
        while not self._stop:
            tick_start = self._now_fn()
            try:
                self.maybe_run_deep_cycle()
            except Exception:
                logger.exception("cognition daemon: tick failed")
            last_tick_at = tick_start  # always advance — spin-bug fix
            sleep_target = last_tick_at + self.config.tick_interval_seconds
            while not self._stop:
                remaining = sleep_target - self._now_fn()
                if remaining <= 0:
                    break
                time.sleep(min(0.5, max(0.05, remaining)))
        logger.info("cognition daemon stopped cleanly")
