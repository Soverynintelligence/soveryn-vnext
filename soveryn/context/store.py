"""SQLite-backed store for ActiveContext records."""

from __future__ import annotations

import json
import sqlite3
from typing import Optional

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


class ActiveContextStore:
    """Persists ActiveContext records in a SQLite database."""

    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path)
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def put(self, context: ActiveContext) -> None:
        """Upsert a context record keyed on topic."""
        self._conn.execute(
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
                context.updated_at,
                context.turn_count,
            ),
        )
        self._conn.commit()

    def get(self, topic: str) -> Optional[ActiveContext]:
        """Return the context for *topic*, or None if absent."""
        row = self._conn.execute(
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
        row = self._conn.execute(
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

    def list_all(self) -> list[ActiveContext]:
        """Return all contexts, newest first."""
        rows = self._conn.execute(
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
