"""Eligibility gates for the Vett patrol daemon.

Mirrors heartbeat.trigger shape with five gates instead of four:
  disabled > interval > backoff > quiet_hours > no_sources

The extra no_sources gate exists because an empty source list is a loud
signal of a config problem (daemon's running but has nothing to do) —
making it a distinct skip reason surfaces it cleanly in vett_patrol_log
instead of hiding behind a downstream failure.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum


class PatrolSkipReason(str, Enum):
    """Why a patrol tick was skipped."""
    DISABLED = "disabled"
    INTERVAL = "interval"
    BACKOFF = "backoff"
    QUIET_HOURS = "quiet_hours"
    NO_SOURCES = "no_sources"


@dataclass(frozen=True)
class PatrolConfig:
    """Daemon config loaded from env at startup. Frozen so per-tick code
    can't mutate it accidentally."""
    enabled: bool
    dry_run: bool
    interval_seconds: int      # default 21600 = 6 hours
    backoff_seconds: int       # default 1800 = 30 min, mirrors heartbeat
    quiet_hours: str           # "" = off; otherwise "HH:MM-HH:MM"
    vnext_base: str            # e.g. http://127.0.0.1:5001
    chat_timeout_seconds: int  # /chat timeout — patrols can fetch many URLs

    @classmethod
    def from_env(cls, env: dict | None = None) -> "PatrolConfig":
        env = env if env is not None else os.environ
        return cls(
            enabled=_parse_bool(env.get("SOVERYN_VETT_PATROL_ENABLED", "true")),
            dry_run=_parse_bool(env.get("SOVERYN_VETT_PATROL_DRY_RUN", "true")),
            interval_seconds=int(env.get("SOVERYN_VETT_PATROL_INTERVAL_SECONDS", "21600")),
            backoff_seconds=int(env.get("SOVERYN_VETT_PATROL_BACKOFF_SECONDS", "1800")),
            quiet_hours=env.get("SOVERYN_VETT_PATROL_QUIET_HOURS", ""),
            vnext_base=env.get("SOVERYN_VETT_PATROL_VNEXT_BASE", "http://127.0.0.1:5001"),
            chat_timeout_seconds=int(env.get("SOVERYN_VETT_PATROL_CHAT_TIMEOUT", "360")),
        )


@dataclass(frozen=True)
class TickEligibility:
    eligible: bool
    skip_reason: PatrolSkipReason | None


def evaluate_tick(
    config: PatrolConfig,
    *,
    now: datetime,
    last_patrol_at: datetime | None,
    last_vett_activity_at: datetime | None,
    source_count: int,
) -> TickEligibility:
    """Apply the five gates in order. First failing gate wins.

    Order: disabled > interval > backoff > quiet_hours > no_sources.
    no_sources is last because if the daemon is otherwise OK, the
    "nothing to do" signal is what we actually want surfaced.
    """
    if not config.enabled:
        return TickEligibility(False, PatrolSkipReason.DISABLED)

    if last_patrol_at is not None:
        elapsed = (now - last_patrol_at).total_seconds()
        if elapsed < config.interval_seconds:
            return TickEligibility(False, PatrolSkipReason.INTERVAL)

    if last_vett_activity_at is not None:
        since_activity = (now - last_vett_activity_at).total_seconds()
        if since_activity < config.backoff_seconds:
            return TickEligibility(False, PatrolSkipReason.BACKOFF)

    if config.quiet_hours and _in_quiet_window(now.time(), config.quiet_hours):
        return TickEligibility(False, PatrolSkipReason.QUIET_HOURS)

    if source_count <= 0:
        return TickEligibility(False, PatrolSkipReason.NO_SOURCES)

    return TickEligibility(True, None)


# ─── Helpers (copied from heartbeat/trigger.py — pure stdlib, no shared dep) ──

def _parse_bool(raw: str) -> bool:
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _in_quiet_window(now_t: time, spec: str) -> bool:
    if "-" not in spec:
        return False
    try:
        start_s, end_s = spec.split("-", 1)
        start_t = _parse_hhmm(start_s.strip())
        end_t = _parse_hhmm(end_s.strip())
    except ValueError:
        return False
    if start_t == end_t:
        return False
    if start_t < end_t:
        return start_t <= now_t < end_t
    return now_t >= start_t or now_t < end_t


def _parse_hhmm(raw: str) -> time:
    parts = raw.split(":")
    if len(parts) != 2:
        raise ValueError(f"expected HH:MM, got {raw!r}")
    h, m = int(parts[0]), int(parts[1])
    return time(h, m)
