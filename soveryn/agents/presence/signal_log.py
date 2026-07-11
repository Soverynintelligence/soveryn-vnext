"""SignalLog — SQLite log of approve/edit/reject decisions (voice signal for DPO export)."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator


DEFAULT_CONNECTION_TIMEOUT_SECONDS = 30.0


class SignalLog:
    """SQLite-backed log of signal decisions (approve/edit/reject).

    Records voice-signal decisions for later DPO export and tuning.
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
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY,
                    draft_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    original_text TEXT NOT NULL,
                    final_text TEXT NOT NULL,
                    reason TEXT,
                    created_at TEXT NOT NULL
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

    def record(
        self,
        draft_id: str,
        action: str,
        original_text: str,
        final_text: str,
        reason: str,
    ) -> None:
        """Record a signal decision (approve/edit/reject).

        Args:
            draft_id: Identifier for the draft being evaluated.
            action: Signal type (approve, edit, or reject).
            original_text: The original text before any edits.
            final_text: The final text (after edits if action is edit, or unchanged if approve/reject).
            reason: User's reasoning for the decision.
        """
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO signals
                (draft_id, action, original_text, final_text, reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (draft_id, action, original_text, final_text, reason, now),
            )

    def all(self) -> list[dict]:
        """Retrieve all signal records.

        Returns:
            List of signal records as dicts (for tests and DPO export).
        """
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, draft_id, action, original_text, final_text, reason, created_at
                FROM signals
                ORDER BY id ASC
                """
            ).fetchall()

        return [dict(row) for row in rows]
