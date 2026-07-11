"""PendingStore — SQLite store for pending presence drafts + the inbound reply queue.

`PresenceDaemonSurface` used to hold pending drafts in an in-process dict,
but Jon's Signal replies (`y`/`n`/edit) arrive in a *separate* process (the
signal bridge, wired in a follow-up task). Two processes share only SQLite,
so both the pending drafts and the inbound reply queue live here:

- `pending_drafts`: draft_id -> a serialized Draft, awaiting Jon's reply.
- `pending_replies`: a FIFO inbox an inbound source enqueues into and the
  presence daemon drains via `take_replies` on every loop iteration.

Mirrors the connection style of the sibling `candidate_store.CandidateStore`.
No wall-clock/random calls happen inside this module — `enqueue_reply` takes
`now` as an explicit argument so callers (and tests) stay deterministic.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from soveryn.agents.presence.drafting import Draft

DEFAULT_CONNECTION_TIMEOUT_SECONDS = 30.0


class PendingStore:
    """SQLite-backed store for pending drafts and the inbound reply queue.

    Schema is bootstrapped idempotently in __init__.
    """

    def __init__(
        self,
        db_path: Path,
        timeout_seconds: float = DEFAULT_CONNECTION_TIMEOUT_SECONDS,
    ) -> None:
        self.db_path = Path(db_path)
        self.timeout_seconds = timeout_seconds
        self._bootstrap_schema()

    def _bootstrap_schema(self) -> None:
        """Create schema tables if they don't exist (idempotent)."""
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_drafts (
                    draft_id TEXT PRIMARY KEY,
                    draft_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_replies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    draft_id TEXT NOT NULL,
                    reply_text TEXT NOT NULL,
                    received_at TEXT NOT NULL
                )
                """
            )

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        """Context manager for database connections."""
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

    def put_draft(self, draft_id: str, draft: Draft) -> None:
        """Serialize `draft` to JSON and upsert it by `draft_id`."""
        draft_json = json.dumps(asdict(draft))
        created_at = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO pending_drafts (draft_id, draft_json, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(draft_id) DO UPDATE SET
                    draft_json = excluded.draft_json,
                    created_at = excluded.created_at
                """,
                (draft_id, draft_json, created_at),
            )

    def get_draft(self, draft_id: str) -> Draft | None:
        """Deserialize and return the Draft stored under `draft_id`, or None."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT draft_json FROM pending_drafts WHERE draft_id = ?",
                (draft_id,),
            ).fetchone()
        if row is None:
            return None
        return Draft(**json.loads(row["draft_json"]))

    def draft_ids(self) -> set[str]:
        """Return the set of all pending draft ids."""
        with self._conn() as conn:
            rows = conn.execute("SELECT draft_id FROM pending_drafts").fetchall()
        return {row["draft_id"] for row in rows}

    def delete_draft(self, draft_id: str) -> None:
        """Delete the pending draft `draft_id`. A no-op if it doesn't exist."""
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM pending_drafts WHERE draft_id = ?",
                (draft_id,),
            )

    def enqueue_reply(self, draft_id: str, reply_text: str, now: str) -> None:
        """Insert a reply row. `now` is caller-supplied for determinism."""
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO pending_replies (draft_id, reply_text, received_at)
                VALUES (?, ?, ?)
                """,
                (draft_id, reply_text, now),
            )

    def take_replies(self) -> list[tuple[str, str]]:
        """Atomically return and delete all queued replies, FIFO order.

        Uses a single connection/transaction so a reply is never returned
        twice, even under concurrent access from another process.
        """
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, draft_id, reply_text
                FROM pending_replies
                ORDER BY id ASC
                """
            ).fetchall()
            ids = [row["id"] for row in rows]
            if ids:
                placeholders = ",".join("?" * len(ids))
                conn.execute(
                    f"DELETE FROM pending_replies WHERE id IN ({placeholders})",
                    ids,
                )
        return [(row["draft_id"], row["reply_text"]) for row in rows]
