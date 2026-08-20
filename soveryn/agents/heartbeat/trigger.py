"""Eligibility gates for heartbeat ticks.

Pure functions, independently testable. The daemon composes them per tick.
Returning TickEligibility instead of raw booleans gives the daemon a
single object to log to heartbeat_log with the skip reason intact.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum


class SkipReason(str, Enum):
    """Why a tick was skipped. NULL skip_reason in heartbeat_log means the
    tick was eligible (and possibly invoked the agent)."""
    DISABLED = "disabled"
    INTERVAL = "interval"
    BACKOFF = "backoff"
    QUIET_HOURS = "quiet_hours"
    # Board/lattice/material snapshot identical to last pulse — do not re-ask
    # the model (2026-08-19: Aetheria looped the same Sandbox note all night).
    UNCHANGED = "unchanged"


@dataclass(frozen=True)
class HeartbeatConfig:
    """Daemon config loaded from env at startup. Frozen so per-tick code
    can't mutate it accidentally."""
    enabled: bool
    dry_run: bool
    interval_seconds: int
    backoff_seconds: int
    quiet_hours: str  # "" = off; otherwise "HH:MM-HH:MM" e.g. "23:00-07:00"

    @classmethod
    def from_env(cls, env: dict | None = None) -> "HeartbeatConfig":
        env = env if env is not None else os.environ
        return cls(
            enabled=_parse_bool(env.get("SOVERYN_HEARTBEAT_ENABLED", "true")),
            dry_run=_parse_bool(env.get("SOVERYN_HEARTBEAT_DRY_RUN", "false")),
            interval_seconds=int(env.get("SOVERYN_HEARTBEAT_INTERVAL_SECONDS", "1800")),
            backoff_seconds=int(env.get("SOVERYN_HEARTBEAT_BACKOFF_SECONDS", "600")),
            quiet_hours=env.get("SOVERYN_HEARTBEAT_QUIET_HOURS", ""),
        )


@dataclass(frozen=True)
class TickEligibility:
    """Result of evaluating a tick. eligible=True means proceed to invoke
    Aetheria; eligible=False means skip and log skip_reason."""
    eligible: bool
    skip_reason: SkipReason | None


def evaluate_tick(
    config: HeartbeatConfig,
    *,
    now: datetime,
    last_heartbeat_at: datetime | None,
    last_aetheria_activity_at: datetime | None,
) -> TickEligibility:
    """Apply the four gates in order. First failing gate wins (returning
    its skip_reason). Order is deliberate: disabled > interval > backoff >
    quiet_hours so the most fundamental skips show up first in the log.

    `now`: caller-provided wall clock (lets tests inject deterministic time).
    `last_heartbeat_at`: timestamp of the most recent successful or attempted
        heartbeat run. None on first run after daemon startup.
    `last_aetheria_activity_at`: timestamp of the most recent Aetheria session
        update (webhook OR user chat). Used for the backoff gate. None means
        no recent activity.
    """
    if not config.enabled:
        return TickEligibility(False, SkipReason.DISABLED)

    if last_heartbeat_at is not None:
        elapsed = (now - last_heartbeat_at).total_seconds()
        if elapsed < config.interval_seconds:
            return TickEligibility(False, SkipReason.INTERVAL)

    if last_aetheria_activity_at is not None:
        since_activity = (now - last_aetheria_activity_at).total_seconds()
        if since_activity < config.backoff_seconds:
            return TickEligibility(False, SkipReason.BACKOFF)

    if config.quiet_hours and _in_quiet_window(now.time(), config.quiet_hours):
        return TickEligibility(False, SkipReason.QUIET_HOURS)

    return TickEligibility(True, None)


# ─── Helpers ────────────────────────────────────────────────────────────────

def _parse_bool(raw: str) -> bool:
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _in_quiet_window(now_t: time, spec: str) -> bool:
    """spec format: 'HH:MM-HH:MM'. Supports wrap-around (e.g., 23:00-07:00
    means 23:00 through 06:59:59). Empty / malformed spec returns False
    (never in window — fail open, the daemon stays alive)."""
    if "-" not in spec:
        return False
    try:
        start_s, end_s = spec.split("-", 1)
        start_t = _parse_hhmm(start_s.strip())
        end_t = _parse_hhmm(end_s.strip())
    except ValueError:
        return False
    if start_t == end_t:
        # Zero-length window — treat as "no quiet hours".
        return False
    if start_t < end_t:
        # Normal window like 02:00-06:00
        return start_t <= now_t < end_t
    # Wrap-around window like 23:00-07:00
    return now_t >= start_t or now_t < end_t


def _parse_hhmm(raw: str) -> time:
    parts = raw.split(":")
    if len(parts) != 2:
        raise ValueError(f"expected HH:MM, got {raw!r}")
    h, m = int(parts[0]), int(parts[1])
    return time(h, m)
