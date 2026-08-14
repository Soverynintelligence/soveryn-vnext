"""SOVERYN Citizens — the commissions queue (charter §9.1, §12.4).

Work the house is owed. A commission is queued by whoever wants it done, claimed
by a worker, and ends `done` with evidence or `failed` with a reason.

The claim is one guarded UPDATE, not read-then-write
----------------------------------------------------
The obvious implementation — SELECT the oldest queued row, then UPDATE it to
running — has a window between the two statements in which a second worker can
select the same row. Both then act. For citizens whose duties touch the real
world that is the work happening twice: Scotty repairing something already
repaired, Vett publishing the same report twice.

So the claim is a single statement whose WHERE clause still contains
`state = 'queued'`. SQLite applies it atomically; the loser updates zero rows
and gets None. Correctness does not depend on how the caller wraps it.

Nothing is allowed to end quietly
---------------------------------
`complete()` requires a result_ref — a path, a session id, something a person
can open. A commission that reports success with no trace of what it produced is
indistinguishable from one that did nothing, and the charter's accountability
duty (§5) is that failures leave a trail.

`running` therefore carries claimed_by and claimed_at, so a commission whose
worker died is *findable* (`abandoned()`) rather than merely lost. That is the
expensive failure: not a crash, which is loud, but a row sitting in `running`
forever while everyone assumes it is in hand.
"""

from __future__ import annotations

import sqlite3
import uuid
from typing import Any

QUEUED = "queued"
RUNNING = "running"
DONE = "done"
FAILED = "failed"


def enqueue(conn: sqlite3.Connection, citizen_id: str, body: str, *, at: str) -> str:
    """Put work on a citizen's queue. Returns the commission id."""
    if not body.strip():
        raise ValueError("a commission needs a body — what is being asked")
    commission_id = str(uuid.uuid4())
    # The foreign key refuses work addressed to a citizen who does not exist,
    # which is the difference between a queue and a place typos go to wait.
    conn.execute(
        "INSERT INTO commissions (id, citizen_id, body, state, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (commission_id, citizen_id, body, QUEUED, at),
    )
    conn.commit()
    return commission_id


def begin_owned(
    conn: sqlite3.Connection,
    citizen_id: str,
    body: str,
    *,
    worker: str,
    at: str,
) -> str:
    """Insert a commission already running and already claimed.

    Used for duty *bookkeeping* (heartbeat pulse, etc.): the work is already
    happening under that worker. The row must never sit in `queued`, where any
    drain worker could steal it, run the literal body as a commission prompt,
    and leave the real pulse unrecorded.

    A pulse is not a request for someone to do work — it is a record of work
    already in flight.
    """
    if not body.strip():
        raise ValueError("a commission needs a body — what is being asked")
    if not worker.strip():
        raise ValueError("begin_owned needs a worker — who holds this work")
    commission_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO commissions "
        "(id, citizen_id, body, state, created_at, claimed_by, claimed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (commission_id, citizen_id, body, RUNNING, at, worker, at),
    )
    conn.commit()
    return commission_id


def claim(
    conn: sqlite3.Connection, citizen_id: str, *, worker: str, at: str
) -> dict[str, Any] | None:
    """Atomically take the oldest queued commission, or return None.

    The guard is `state = 'queued'` inside the UPDATE itself. Two workers racing
    for one commission both run this; exactly one changes a row.
    """
    # RETURNING makes the update and the read one statement, so the row handed
    # back is provably the row this claim took.
    #
    # The first version updated, then re-SELECTed by (worker, claimed_at). That
    # key is not unique: a worker claiming several commissions at the same
    # timestamp got its FIRST row back every time. A 12-thread race over 200
    # commissions marked all 200 running while returning only 2 to workers, both
    # of them twice — the exact double-execution this function exists to
    # prevent, invisible to a sequential test.
    row = conn.execute(
        """
        UPDATE commissions
           SET state = ?, claimed_by = ?, claimed_at = ?
         WHERE id = (
               SELECT id FROM commissions
                WHERE citizen_id = ? AND state = ?
                ORDER BY created_at ASC, id ASC
                LIMIT 1
         )
           AND state = ?
        RETURNING *
        """,
        (RUNNING, worker, at, citizen_id, QUEUED, QUEUED),
    ).fetchone()
    conn.commit()
    return dict(row) if row else None


def _require_running(conn: sqlite3.Connection, commission_id: str) -> None:
    row = conn.execute(
        "SELECT state FROM commissions WHERE id = ?", (commission_id,)
    ).fetchone()
    if row is None:
        raise KeyError(commission_id)
    if row["state"] != RUNNING:
        # Finishing something that was never claimed, or finishing it twice,
        # means two parties disagree about who holds the work. Refuse loudly.
        raise ValueError(
            f"commission {commission_id} is {row['state']}, not {RUNNING} — "
            "only claimed work can be completed or failed"
        )


def complete(
    conn: sqlite3.Connection, commission_id: str, *, result_ref: str, at: str
) -> None:
    """Finish with evidence. `result_ref` is not optional, deliberately."""
    if not result_ref.strip():
        raise ValueError(
            "complete() needs a result_ref — a path or id someone can open. "
            "Success with no trace cannot be told apart from doing nothing."
        )
    _require_running(conn, commission_id)
    conn.execute(
        "UPDATE commissions SET state = ?, result_ref = ?, completed_at = ? "
        "WHERE id = ?",
        (DONE, result_ref, at, commission_id),
    )
    conn.commit()


def fail(conn: sqlite3.Connection, commission_id: str, *, error: str, at: str) -> None:
    _require_running(conn, commission_id)
    conn.execute(
        "UPDATE commissions SET state = ?, error = ?, completed_at = ? WHERE id = ?",
        (FAILED, error or "failed without a reason", at, commission_id),
    )
    conn.commit()


def abandoned(conn: sqlite3.Connection, *, claimed_before: str) -> list[dict[str, Any]]:
    """Commissions still `running` that were claimed before a cutoff.

    This is how a dead worker becomes visible. The caller chooses the cutoff,
    because how long is too long depends on the duty — a patrol is minutes, a
    research commission can be an hour.
    """
    rows = conn.execute(
        "SELECT * FROM commissions WHERE state = ? AND claimed_at IS NOT NULL "
        "AND claimed_at <= ? ORDER BY claimed_at ASC",
        (RUNNING, claimed_before),
    ).fetchall()
    return [dict(r) for r in rows]


def requeue(conn: sqlite3.Connection, commission_id: str, *, at: str, reason: str) -> None:
    """Return abandoned work to the queue, keeping the record of the attempt.

    The previous claim is cleared so another worker can take it, but `error`
    keeps why — otherwise a commission that failed repeatedly looks identical to
    one that was never tried.
    """
    row = conn.execute(
        "SELECT state, error, claimed_by FROM commissions WHERE id = ?",
        (commission_id,),
    ).fetchone()
    if row is None:
        raise KeyError(commission_id)
    if row["state"] != RUNNING:
        raise ValueError(f"commission {commission_id} is {row['state']}, not {RUNNING}")

    note = f"[{at}] requeued from {row['claimed_by'] or 'unknown worker'}: {reason}"
    trail = f"{row['error']}\n{note}" if row["error"] else note
    conn.execute(
        "UPDATE commissions SET state = ?, claimed_by = NULL, claimed_at = NULL, "
        "error = ? WHERE id = ?",
        (QUEUED, trail, commission_id),
    )
    conn.commit()


def for_citizen(
    conn: sqlite3.Connection,
    citizen_id: str,
    *,
    limit: int = 50,
    state: str | None = None,
) -> list[dict[str, Any]]:
    if state is None:
        rows = conn.execute(
            "SELECT * FROM commissions WHERE citizen_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (citizen_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM commissions WHERE citizen_id = ? AND state = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (citizen_id, state, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get(conn: sqlite3.Connection, commission_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM commissions WHERE id = ?", (commission_id,)
    ).fetchone()
    return dict(row) if row else None


def is_running(conn: sqlite3.Connection, citizen_id: str) -> bool:
    """True if this citizen already has a commission in flight."""
    row = conn.execute(
        "SELECT 1 FROM commissions WHERE citizen_id = ? AND state = ? LIMIT 1",
        (citizen_id, RUNNING),
    ).fetchone()
    return row is not None


def cancel(
    conn: sqlite3.Connection, commission_id: str, *, at: str, reason: str = "cancelled"
) -> dict[str, Any]:
    """Cancel a still-queued commission. Running work is refused.

    There is no separate `cancelled` state in the schema: cancelled work is
    recorded as `failed` with a clear reason so the trail stays findable and
    the worker never claims it.
    """
    row = get(conn, commission_id)
    if row is None:
        raise KeyError(commission_id)
    if row["state"] != QUEUED:
        raise ValueError(
            f"commission {commission_id} is {row['state']}, not {QUEUED} — "
            "only queued work can be cancelled"
        )
    note = reason.strip() or "cancelled"
    conn.execute(
        "UPDATE commissions SET state = ?, error = ?, completed_at = ? WHERE id = ?",
        (FAILED, note, at, commission_id),
    )
    conn.commit()
    updated = get(conn, commission_id)
    assert updated is not None
    return updated
