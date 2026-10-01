"""SQLite store for Web Push subscriptions (one phone / many endpoints)."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_DB = Path.home() / "soveryn_vnext" / "data" / "memory" / "webpush.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS push_subscriptions (
    endpoint TEXT PRIMARY KEY,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    user_agent TEXT,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);
"""


def _db_path() -> Path:
    raw = os.environ.get("SOVERYN_WEBPUSH_DB", "").strip()
    return Path(raw) if raw else _DEFAULT_DB


def connect(path: Path | None = None) -> sqlite3.Connection:
    p = path or _db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    return conn


def upsert_subscription(
    *,
    endpoint: str,
    p256dh: str,
    auth: str,
    user_agent: str = "",
    path: Path | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with connect(path) as conn:
        conn.execute(
            """
            INSERT INTO push_subscriptions
                (endpoint, p256dh, auth, user_agent, created_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(endpoint) DO UPDATE SET
                p256dh=excluded.p256dh,
                auth=excluded.auth,
                user_agent=excluded.user_agent,
                last_seen_at=excluded.last_seen_at
            """,
            (endpoint, p256dh, auth, user_agent or "", now, now),
        )
        conn.commit()


def remove_subscription(endpoint: str, *, path: Path | None = None) -> bool:
    with connect(path) as conn:
        cur = conn.execute(
            "DELETE FROM push_subscriptions WHERE endpoint=?", (endpoint,)
        )
        conn.commit()
        return cur.rowcount > 0


def list_subscriptions(*, path: Path | None = None) -> list[dict[str, Any]]:
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT endpoint, p256dh, auth, user_agent, created_at, last_seen_at "
            "FROM push_subscriptions ORDER BY last_seen_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def subscription_info(row: dict[str, Any]) -> dict[str, Any]:
    """Shape expected by pywebpush.webpush(subscription_info=...)."""
    return {
        "endpoint": row["endpoint"],
        "keys": {"p256dh": row["p256dh"], "auth": row["auth"]},
    }


def dump_debug(*, path: Path | None = None) -> str:
    return json.dumps({"count": len(list_subscriptions(path=path))}, indent=2)
