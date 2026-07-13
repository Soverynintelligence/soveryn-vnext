"""Once-per-day, morning-only nudge inviting Aetheria to compose her single
daily X post.

The heartbeat daemon has a legitimate wall clock, so this is the one place
we read local time (`datetime.now()` in the daemon). Per the codebase's
determinism discipline, the daemon reads `now` ONCE and passes it in — all
of the once/day + AM + state logic lives in `should_nudge`, a pure function
with no clock and no I/O.

State (the last date we nudged) persists in a tiny JSON file so a daemon
restart mid-day doesn't re-nudge. Both readers/writers are best-effort by
contract: a state-file problem must degrade to "don't nudge", never break
the heartbeat tick.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# First heartbeat tick each day at/after this local hour gets the invite.
DEFAULT_DAILY_POST_HOUR = 8

# The nudge is an INVITATION, not a command — she does worse with heavy rules,
# so keep it light and skippable. She composes via her EXISTING post_to_x tool
# (Stage 0 stages it for Jon to approve); no new posting path is introduced.
DAILY_POST_INVITE = (
    "Morning — your window for today's one post. If a thought's worth sharing "
    "publicly, compose a single original tweet (it'll stage for Jon to approve). "
    "Just one; skip it freely if nothing's calling to you."
)

_STATE_KEY = "last_post_invite_date"


def should_nudge(
    *,
    now: datetime,
    last_invite_date: str | None,
    hour_threshold: int,
) -> bool:
    """Pure predicate: should the daily-post invite fire on this tick?

    True when BOTH hold:
      - the local hour is at/after `hour_threshold` (morning gate), and
      - we have not already nudged today — i.e. `now`'s calendar date is
        strictly later than `last_invite_date` (an "YYYY-MM-DD" string, or
        None if we've never nudged).

    No wall clock, no I/O — `now` is injected by the caller. ISO date strings
    (YYYY-MM-DD) sort lexicographically the same as chronologically, so the
    string compare is a correct date compare.
    """
    if now.hour < hour_threshold:
        return False
    today = now.date().isoformat()
    if last_invite_date is None:
        return True
    return today > last_invite_date


def read_last_invite_date(path: Path) -> str | None:
    """Return the persisted last-nudged date ("YYYY-MM-DD"), or None.

    Best-effort: a missing/corrupt/unreadable state file returns None (treated
    by `should_nudge` as "never nudged"), never raises.
    """
    try:
        raw = Path(path).read_text()
    except FileNotFoundError:
        return None
    except OSError:
        logger.exception("daily-post state read failed; treating as unset")
        return None
    try:
        value = json.loads(raw).get(_STATE_KEY)
    except (ValueError, AttributeError):
        logger.exception("daily-post state file corrupt; treating as unset")
        return None
    return value if isinstance(value, str) else None


def write_last_invite_date(path: Path, date_str: str) -> None:
    """Persist `date_str` as the last-nudged date. Best-effort (logs on error)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({_STATE_KEY: date_str}))
