"""Record a citizen's duty tick as a commission (charter §12.5).

The heartbeat is migrated by being **observed**, not by being **driven**.

The charter asks for the heartbeat on the commission path "without changing
product feel", and there are two ways to read that. The dangerous one is to make
the queue the thing that decides when she acts — that puts a database between
Aetheria and her own initiative, and the recorded principle is to free her, not
cage her. The safe one, taken here, is that each pulse she runs is *written down*
as a commission: queued, claimed, and closed with what happened.

What that buys, concretely:

  * `on_duty` becomes derivable — a citizen with a running commission is working
    right now, which is the state the console needs and the registry could not
    otherwise know.
  * every pulse leaves a trail, satisfying the accountability duty (§5).
  * a daemon that dies mid-pulse leaves a `running` row that `abandoned()` can
    find. The 26-hour silent outage of 2026-07-26 looked exactly like an agent
    choosing not to act; a stalled commission with a claim timestamp would have
    said "she has been mid-pulse for 26 hours" instead.

The invariant that matters more than any of it
----------------------------------------------
**Bookkeeping may never break the heartbeat.** Every failure in this module is
swallowed and logged. If the registry is missing, locked, corrupt, or the schema
is older than this code, the wrapped work still runs and the pulse still happens.
A monitoring layer that can take down the thing it monitors is worse than no
monitoring layer, and this one wraps her spontaneous initiation.

The only exception that propagates is the one raised by the wrapped work itself,
which is re-raised untouched so the caller's own error handling is unchanged.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from soveryn.citizens import commissions
from soveryn.citizens.registry import connect

logger = logging.getLogger(__name__)


@contextmanager
def record_pulse(
    db_path: str | Path | None,
    citizen_id: str,
    body: str,
    *,
    worker: str,
    now: str,
    result_ref: str = "",
) -> Iterator[str | None]:
    """Wrap a duty tick so it appears in the commissions queue.

    Yields the commission id, or None if the pulse could not be recorded — the
    caller does not need to care which, and must not branch on it for anything
    load-bearing.
    """
    commission_id: str | None = None
    conn: sqlite3.Connection | None = None
    ctx = None

    if db_path is not None:
        try:
            ctx = connect(db_path)
            conn = ctx.__enter__()
            commission_id = commissions.enqueue(conn, citizen_id, body, at=now)
            claimed = commissions.claim(conn, citizen_id, worker=worker, at=now)
            # A claim can legitimately return another commission — anything
            # already queued for this citizen is older and wins. That is correct
            # queue behaviour, but it means the row we are about to close is the
            # claimed one, not necessarily the one just enqueued.
            if claimed is not None:
                commission_id = claimed["id"]
            else:
                commission_id = None
        except Exception:
            logger.warning(
                "pulse bookkeeping failed to open; the tick proceeds unrecorded",
                exc_info=True,
            )
            commission_id = None

    try:
        yield commission_id
    except BaseException as exc:
        _close(conn, commission_id, ok=False, at=now, detail=repr(exc))
        _release(ctx)
        raise                      # the caller's error handling is untouched
    else:
        _close(conn, commission_id, ok=True, at=now,
               detail=result_ref or f"pulse:{worker}@{now}")
        _release(ctx)


def _close(conn, commission_id, *, ok: bool, at: str, detail: str) -> None:
    if conn is None or commission_id is None:
        return
    try:
        if ok:
            commissions.complete(conn, commission_id, result_ref=detail, at=at)
        else:
            commissions.fail(conn, commission_id, error=detail, at=at)
    except Exception:
        logger.warning("pulse bookkeeping failed to close %s", commission_id,
                       exc_info=True)


def _release(ctx) -> None:
    if ctx is None:
        return
    try:
        ctx.__exit__(None, None, None)
    except Exception:
        logger.warning("pulse bookkeeping failed to close the registry",
                       exc_info=True)
