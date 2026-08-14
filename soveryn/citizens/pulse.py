"""Record a citizen's duty tick as a commission (charter §12.5).

The heartbeat is migrated by being **observed**, not by being **driven**.

The charter asks for the heartbeat on the commission path "without changing
product feel", and there are two ways to read that. The dangerous one is to make
the queue the thing that decides when she acts — that puts a database between
Aetheria and her own initiative, and the recorded principle is to free her, not
cage her. The safe one, taken here, is that each pulse she runs is *written down*
as a commission already in flight: owned by the heartbeat worker from the first
insert, closed with what happened.

What that buys, concretely:

  * `on_duty` becomes derivable — a citizen with a running commission is working
    right now, which is the state the console needs and the registry could not
    otherwise know.
  * every pulse leaves a trail, satisfying the accountability duty (§5).
  * a daemon that dies mid-pulse leaves a `running` row that `abandoned()` can
    find. The 26-hour silent outage of 2026-07-26 looked exactly like an agent
    choosing not to act; a stalled commission with a claim timestamp would have
    said "she has been mid-pulse for 26 hours" instead.

Why the row never sits in `queued`
----------------------------------
A pulse is not a request for the citizens-runtime to do work. It is a record of
work the heartbeat is already doing. The first implementation did
`enqueue()` then `claim()`, which left a window where the drain worker could
steal the row, run AgentLoop on the literal body "heartbeat pulse", write a
junk outbox file, and leave the real pulse unrecorded. That is a when, not an
if, at 48 pulses a day. So the insert is `begin_owned` — already `running`,
already claimed by the duty worker.

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
from soveryn.citizens.registry import OBSERVED_PRESENT, connect, observe

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
    """Wrap a duty tick so it appears as an owned running commission.

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
            # Already running + owned — never enters the drainable queue.
            commission_id = commissions.begin_owned(
                conn, citizen_id, body, worker=worker, at=now
            )
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
        # Phase 3: a completed pulse is evidence she is present — advance
        # last_seen without waiting for the next census. Best-effort only.
        _note_present(conn, citizen_id, at=now, worker=worker)
        _release(ctx)


def _note_present(conn, citizen_id: str, *, at: str, worker: str) -> None:
    if conn is None:
        return
    try:
        observe(
            conn,
            citizen_id,
            OBSERVED_PRESENT,
            at=at,
            detail=f"duty pulse via {worker}",
        )
    except Exception:
        logger.warning(
            "pulse bookkeeping failed to observe %s present", citizen_id,
            exc_info=True,
        )


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
