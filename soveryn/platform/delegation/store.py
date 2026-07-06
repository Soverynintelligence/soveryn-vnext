"""SOVERYN vNext — delegation task store.

SQLite-backed store for Scotty-delegated tasks and their lifecycle status.
Path-injected; no module-level DB connection. Mirrors the connection-per-call
pattern of soveryn.platform.documents.store.

Legal status transitions (the honesty invariant):
    dispatched  → executing
    dispatched  → failed
    executing   → in_review
    executing   → failed
    in_review   → landed
    in_review   → rejected

Terminal states (landed / rejected / failed) cannot transition further.
"""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator


# ─── Schema ──────────────────────────────────────────────────────────────────

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS delegation_tasks (
    id               TEXT PRIMARY KEY,
    dispatched_by    TEXT NOT NULL,
    objective        TEXT NOT NULL,
    scope            TEXT NOT NULL,
    acceptance       TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'dispatched',
    worktree_path    TEXT,
    branch           TEXT,
    diff             TEXT,
    test_output      TEXT,
    summary          TEXT,
    review_feedback  TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_delegation_status     ON delegation_tasks(status);
CREATE INDEX IF NOT EXISTS idx_delegation_updated_at ON delegation_tasks(updated_at DESC);
"""

# (current_status, new_status) pairs that are allowed
_LEGAL: frozenset[tuple[str, str]] = frozenset({
    ("dispatched", "executing"),
    ("dispatched", "failed"),
    ("executing",  "in_review"),
    ("executing",  "failed"),
    ("in_review",  "landed"),
    ("in_review",  "rejected"),
})

_TERMINAL: frozenset[str] = frozenset({"landed", "rejected", "failed"})

DEFAULT_CONNECTION_TIMEOUT_SECONDS = 30.0


# ─── Exception ───────────────────────────────────────────────────────────────

class IllegalTransition(Exception):
    """Raised when set_status is called with a transition not in _LEGAL."""


# ─── Dataclass ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Task:
    id: str
    dispatched_by: str
    objective: str
    scope: str
    acceptance: str
    status: str
    worktree_path: str | None
    branch: str | None
    diff: str | None
    test_output: str | None
    summary: str | None
    review_feedback: str | None
    created_at: str
    updated_at: str


def _row_to_task(row: sqlite3.Row) -> Task:
    return Task(
        id=row["id"],
        dispatched_by=row["dispatched_by"],
        objective=row["objective"],
        scope=row["scope"],
        acceptance=row["acceptance"],
        status=row["status"],
        worktree_path=row["worktree_path"],
        branch=row["branch"],
        diff=row["diff"],
        test_output=row["test_output"],
        summary=row["summary"],
        review_feedback=row["review_feedback"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# ─── Store ───────────────────────────────────────────────────────────────────

class DelegationStore:
    """SQLite-backed delegation task persistence. Path-injected; no module state."""

    def __init__(
        self,
        db_path: Path | str,
        timeout_seconds: float = DEFAULT_CONNECTION_TIMEOUT_SECONDS,
    ) -> None:
        self.db_path = Path(db_path)
        self.timeout_seconds = timeout_seconds
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=self.timeout_seconds)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(_SCHEMA_SQL)

    # ─── Public API ───────────────────────────────────────────────────────────

    def create_task(
        self,
        *,
        dispatched_by: str,
        objective: str,
        scope: str,
        acceptance: str,
    ) -> str:
        """Insert a new task row with status 'dispatched'. Returns the new task id (uuid4)."""
        task_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO delegation_tasks "
                "(id, dispatched_by, objective, scope, acceptance, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'dispatched', ?, ?)",
                (task_id, dispatched_by, objective, scope, acceptance, now, now),
            )
        return task_id

    def get_task(self, task_id: str) -> Task | None:
        """Return the Task with the given id, or None if not found."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM delegation_tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
        return _row_to_task(row) if row else None

    def list_tasks(self, *, status: str | None = None) -> tuple[Task, ...]:
        """Return tasks newest-first by updated_at; optional status filter."""
        if status is not None:
            sql = "SELECT * FROM delegation_tasks WHERE status = ? ORDER BY updated_at DESC"
            params: list[str] = [status]
        else:
            sql = "SELECT * FROM delegation_tasks ORDER BY updated_at DESC"
            params = []

        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return tuple(_row_to_task(r) for r in rows)

    def set_status(self, task_id: str, status: str) -> bool:
        """Transition task to a new status.

        Raises IllegalTransition if the (current→new) pair is not in _LEGAL,
        or if the task is already in a terminal state.
        Returns True if a row was updated, False if task_id not found.
        """
        task = self.get_task(task_id)
        if task is None:
            return False

        current = task.status

        # Terminal states cannot transition further
        if current in _TERMINAL:
            raise IllegalTransition(
                f"Task {task_id} is in terminal state '{current}'; cannot transition to '{status}'"
            )

        if (current, status) not in _LEGAL:
            raise IllegalTransition(
                f"Illegal transition '{current}' → '{status}' for task {task_id}"
            )

        now = datetime.now().isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE delegation_tasks SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, task_id),
            )
        return cur.rowcount > 0

    def set_execution(self, task_id: str, *, worktree_path: str, branch: str) -> bool:
        """Record worktree path and branch once execution begins.
        Returns True if a row was updated."""
        now = datetime.now().isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE delegation_tasks SET worktree_path = ?, branch = ?, updated_at = ? WHERE id = ?",
                (worktree_path, branch, now, task_id),
            )
        return cur.rowcount > 0

    def set_result(self, task_id: str, *, diff: str, test_output: str, summary: str) -> bool:
        """Record the diff, test output, and summary after Scotty completes work.
        Returns True if a row was updated."""
        now = datetime.now().isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE delegation_tasks SET diff = ?, test_output = ?, summary = ?, updated_at = ? WHERE id = ?",
                (diff, test_output, summary, now, task_id),
            )
        return cur.rowcount > 0

    def set_review(self, task_id: str, *, review_feedback: str) -> bool:
        """Record review feedback after Aetheria inspects the result.
        Returns True if a row was updated."""
        now = datetime.now().isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE delegation_tasks SET review_feedback = ?, updated_at = ? WHERE id = ?",
                (review_feedback, now, task_id),
            )
        return cur.rowcount > 0
