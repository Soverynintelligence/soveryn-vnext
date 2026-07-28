"""SQLite-backed store for ActiveContext records."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from .active_context import ActiveContext

_SCHEMA = """
CREATE TABLE IF NOT EXISTS active_context (
    topic       TEXT PRIMARY KEY,
    summary     TEXT NOT NULL,
    rail        TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    turn_count  INTEGER NOT NULL DEFAULT 0
);
"""


def _normalize_utc(ts: str) -> str:
    """Normalize an ISO-8601 timestamp string to UTC with trailing Z.

    Accepts timestamps with timezone offsets (e.g. '+09:00') or 'Z',
    and returns a UTC string ending in 'Z' so that lexicographic ordering
    equals chronological ordering.
    """
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt_utc = dt.astimezone(timezone.utc)
    return dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")


class ActiveContextStore:
    """Persists ActiveContext records in a SQLite database."""

    def __init__(
        self,
        db_path: Path | str,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.db_path = Path(db_path)
        self.timeout_seconds = timeout_seconds
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=self.timeout_seconds)
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
            conn.executescript(_SCHEMA)

    def put(self, context: ActiveContext) -> None:
        """Upsert a context record keyed on topic."""
        updated_at = _normalize_utc(context.updated_at)
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO active_context (topic, summary, rail, updated_at, turn_count)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(topic) DO UPDATE SET
                    summary    = excluded.summary,
                    rail       = excluded.rail,
                    updated_at = excluded.updated_at,
                    turn_count = excluded.turn_count;
                """,
                (
                    context.topic,
                    context.summary,
                    context.rail,
                    updated_at,
                    context.turn_count,
                ),
            )

    def get(self, topic: str) -> Optional[ActiveContext]:
        """Return the context for *topic*, or None if absent."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT topic, summary, rail, updated_at, turn_count FROM active_context WHERE topic = ?",
                (topic,),
            ).fetchone()
        if row is None:
            return None
        return ActiveContext(
            topic=row[0],
            summary=row[1],
            rail=row[2],
            updated_at=row[3],
            turn_count=row[4],
        )

    def latest(self) -> Optional[ActiveContext]:
        """Return the most recently updated context, or None."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT topic, summary, rail, updated_at, turn_count FROM active_context ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return ActiveContext(
            topic=row[0],
            summary=row[1],
            rail=row[2],
            updated_at=row[3],
            turn_count=row[4],
        )

    def delete(self, topic: str) -> bool:
        """Remove the record for *topic*. Returns True if a row was removed.

        Added 2026-07-28 for ActiveContextService.clear_action: an action that
        has been resolved must leave the live context, or "not yet heard back
        on" becomes a lie that grows.
        """
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM active_context WHERE topic = ?", (topic,)
            )
            return cur.rowcount > 0

    def list_all(self) -> list[ActiveContext]:
        """Return all contexts, newest first."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT topic, summary, rail, updated_at, turn_count FROM active_context ORDER BY updated_at DESC"
            ).fetchall()
        return [
            ActiveContext(
                topic=row[0],
                summary=row[1],
                rail=row[2],
                updated_at=row[3],
                turn_count=row[4],
            )
            for row in rows
        ]
