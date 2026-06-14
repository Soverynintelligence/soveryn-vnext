"""Telemetry persistence API.

JSONL is the canonical append-only record. SQLite is a query mirror written in
the same call after the JSONL append; if a process dies in that narrow window,
the mirror can be rebuilt from JSONL.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from soveryn.platform.telemetry.events import TelemetryEvent, TelemetryLevel

DEFAULT_TELEMETRY_DIR = Path.home() / "soveryn_vnext" / "data" / "telemetry"
VALID_LEVELS = {"debug", "info", "warning", "error"}

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    event_type TEXT NOT NULL,
    level TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_telemetry_source_created ON telemetry(source, created_at);
CREATE INDEX IF NOT EXISTS idx_telemetry_type_created ON telemetry(event_type, created_at);
CREATE INDEX IF NOT EXISTS idx_telemetry_level_created ON telemetry(level, created_at);
"""


class TelemetryError(Exception):
    """Raised for invalid telemetry writes or queries."""


class TelemetryStore:
    """JSONL + SQLite telemetry store."""

    def __init__(self, telemetry_dir: Path | None = None) -> None:
        self.telemetry_dir = Path(telemetry_dir) if telemetry_dir is not None else _default_dir()
        self.telemetry_dir.mkdir(parents=True, exist_ok=True)
        self.jsonl_path = self.telemetry_dir / "telemetry.jsonl"
        self.sqlite_path = self.telemetry_dir / "telemetry.db"
        self._init_schema()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.sqlite_path))
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

    def log(
        self,
        *,
        source: str,
        event_type: str,
        level: TelemetryLevel = "info",
        payload: dict[str, Any] | None = None,
    ) -> TelemetryEvent:
        event = _build_event(source=source, event_type=event_type, level=level, payload=payload)
        encoded_payload = _json_dump(event.payload)
        line = json.dumps({
            "source": event.source,
            "event_type": event.event_type,
            "level": event.level,
            "payload": event.payload,
            "created_at": event.created_at,
        }, sort_keys=True)
        with self.jsonl_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO telemetry (source, event_type, level, payload, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (event.source, event.event_type, event.level, encoded_payload, event.created_at),
            )
        return event

    def query(self, filters: dict[str, Any] | None = None, *, limit: int = 100) -> tuple[TelemetryEvent, ...]:
        filters = dict(filters or {})
        if limit <= 0:
            return ()
        clauses: list[str] = []
        params: list[Any] = []
        for key in ("source", "event_type", "level"):
            if key in filters:
                clauses.append(f"{key} = ?")
                params.append(str(filters[key]))
        if "since" in filters:
            clauses.append("created_at >= ?")
            params.append(str(filters["since"]))
        if "until" in filters:
            clauses.append("created_at <= ?")
            params.append(str(filters["until"]))
        unknown = set(filters) - {"source", "event_type", "level", "since", "until"}
        if unknown:
            raise TelemetryError(f"unknown telemetry query filters: {sorted(unknown)}")
        sql = "SELECT * FROM telemetry"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id ASC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return tuple(_row_to_event(row) for row in rows)


def log(
    *,
    source: str,
    event_type: str,
    level: TelemetryLevel = "info",
    payload: dict[str, Any] | None = None,
) -> TelemetryEvent:
    return TelemetryStore().log(source=source, event_type=event_type, level=level, payload=payload)


def query(filters: dict[str, Any] | None = None, *, limit: int = 100) -> tuple[TelemetryEvent, ...]:
    return TelemetryStore().query(filters, limit=limit)


def _default_dir() -> Path:
    override = os.environ.get("SOVERYN_TELEMETRY_DIR")
    return Path(override) if override else DEFAULT_TELEMETRY_DIR


def _build_event(
    *,
    source: str,
    event_type: str,
    level: TelemetryLevel,
    payload: dict[str, Any] | None,
) -> TelemetryEvent:
    if not source.strip():
        raise TelemetryError("source must be non-empty")
    if not event_type.strip():
        raise TelemetryError("event_type must be non-empty")
    if level not in VALID_LEVELS:
        raise TelemetryError(f"level must be one of {sorted(VALID_LEVELS)}")
    payload_dict = dict(payload or {})
    _json_dump(payload_dict)
    return TelemetryEvent(
        source=source.strip(),
        event_type=event_type.strip(),
        level=level,
        payload=payload_dict,
    )


def _json_dump(payload: dict[str, Any]) -> str:
    try:
        return json.dumps(payload, sort_keys=True)
    except TypeError as exc:
        raise TelemetryError(f"payload is not JSON-serializable: {exc}") from exc


def _row_to_event(row: sqlite3.Row) -> TelemetryEvent:
    return TelemetryEvent(
        source=row["source"],
        event_type=row["event_type"],
        level=row["level"],
        payload=json.loads(row["payload"]),
        created_at=row["created_at"],
    )
