"""SQLite-WAL platform event log."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from soveryn.platform.bus.events import BusError, Event, EventType, validate_event_type

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    actor TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_type_id ON events(event_type, id);
"""


class SQLiteBus:
    """SQLite-backed event log with cursor-based polling.

    The database is opened per operation and configured for WAL mode. This is
    enough for the low-volume SOVERYN agent bus without adding infrastructure.
    """

    def __init__(self, db_path: Path, timeout_seconds: float = 30.0) -> None:
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

    def publish(self, event_type: EventType, payload: dict[str, Any], actor: str) -> Event:
        checked_type = validate_event_type(event_type)
        payload_json = _json_dump(payload)
        event = Event(id=0, event_type=checked_type, payload=dict(payload), actor=actor)
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO events (event_type, payload, actor, created_at) VALUES (?, ?, ?, ?)",
                (event.event_type, payload_json, event.actor, event.created_at),
            )
            event_id = int(cur.lastrowid)
        return Event(
            id=event_id,
            event_type=event.event_type,
            payload=event.payload,
            actor=event.actor,
            created_at=event.created_at,
        )

    def subscribe(
        self,
        event_types: Iterable[EventType],
        cursor: int = 0,
        *,
        limit: int | None = None,
    ) -> tuple[Event, ...]:
        wanted = tuple(validate_event_type(event_type) for event_type in event_types)
        if not wanted:
            return ()
        placeholders = ",".join("?" for _ in wanted)
        params: list[Any] = [cursor, *wanted]
        sql = (
            "SELECT * FROM events "
            f"WHERE id > ? AND event_type IN ({placeholders}) "
            "ORDER BY id ASC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return tuple(_row_to_event(row) for row in rows)


def _json_dump(payload: dict[str, Any]) -> str:
    try:
        return json.dumps(payload, sort_keys=True)
    except TypeError as exc:
        raise BusError(f"payload is not JSON-serializable: {exc}") from exc


def _row_to_event(row: sqlite3.Row) -> Event:
    return Event(
        id=int(row["id"]),
        event_type=validate_event_type(row["event_type"]),
        payload=json.loads(row["payload"]),
        actor=row["actor"],
        created_at=row["created_at"],
    )
