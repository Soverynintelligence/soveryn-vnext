"""Eligibility gates for the dream daemon. Pure functions, independently testable.

Five gates per spec, in order. First failing gate wins:
  disabled > outside_quiet_hours > already_dreamed_this_window >
  activity_backoff > nothing_to_dream_about
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import Enum

from soveryn.agents.dream.config import DreamConfig


class DreamSkipReason(str, Enum):
    DISABLED = "disabled"
    OUTSIDE_QUIET_HOURS = "outside_quiet_hours"
    ALREADY_DREAMED = "already_dreamed"
    ACTIVITY_BACKOFF = "activity_backoff"
    NOTHING_TO_DREAM_ABOUT = "nothing_to_dream_about"


@dataclass(frozen=True)
class TickEligibility:
    eligible: bool
    skip_reason: DreamSkipReason | None


def evaluate_tick(
    config: DreamConfig,
    *,
    now: datetime,
    last_dream_at: datetime | None,
    last_activity_at: datetime | None,
    new_node_count_since_last_dream: int,
) -> TickEligibility:
    """Apply the five gates in order. First failing gate wins."""
    if not config.enabled:
        return TickEligibility(False, DreamSkipReason.DISABLED)

    if not in_quiet_window(now.time(), config.quiet_hours):
        return TickEligibility(False, DreamSkipReason.OUTSIDE_QUIET_HOURS)

    # One run per window opening — if the last dream was inside the
    # currently-open window (or within the last ~12 hours, generous bound
    # to handle wrap-around windows), skip.
    if last_dream_at is not None:
        elapsed_hours = (now - last_dream_at).total_seconds() / 3600
        if elapsed_hours < 12:
            return TickEligibility(False, DreamSkipReason.ALREADY_DREAMED)

    if last_activity_at is not None:
        since_activity = (now - last_activity_at).total_seconds()
        if since_activity < config.activity_backoff_seconds:
            return TickEligibility(False, DreamSkipReason.ACTIVITY_BACKOFF)

    if new_node_count_since_last_dream <= 0:
        return TickEligibility(False, DreamSkipReason.NOTHING_TO_DREAM_ABOUT)

    return TickEligibility(True, None)


def in_quiet_window(now_t: time, spec: str) -> bool:
    """spec format: 'HH:MM-HH:MM'. Supports wrap-around (e.g., 23:00-07:00
    means 23:00 through 06:59:59). Empty / malformed spec returns False."""
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
    # Wrap-around window
    return now_t >= start_t or now_t < end_t


def _parse_hhmm(raw: str) -> time:
    parts = raw.split(":")
    if len(parts) != 2:
        raise ValueError(f"expected HH:MM, got {raw!r}")
    h, m = int(parts[0]), int(parts[1])
    return time(h, m)
