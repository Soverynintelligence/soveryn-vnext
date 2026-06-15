"""SQLite substrate for the messenger.

Tables created at first use; idempotent. Mirrors the ConversationStore
pattern — one DB file, simple SQL, no ORM.
"""
from __future__ import annotations
import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS m_devices (
    device_id    TEXT PRIMARY KEY,
    secret_hash  TEXT NOT NULL,
    label        TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    last_seen_at TEXT,
    revoked_at   TEXT
);

CREATE TABLE IF NOT EXISTS m_pairing_tokens (
    token        TEXT PRIMARY KEY,
    label        TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    claimed_by   TEXT,
    claimed_at   TEXT
);

CREATE TABLE IF NOT EXISTS m_threads (
    thread_id     TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL,
    agent         TEXT NOT NULL,
    session_id    TEXT NOT NULL UNIQUE,
    title         TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    last_activity TEXT NOT NULL,
    muted         INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_threads_user ON m_threads(user_id);
CREATE INDEX IF NOT EXISTS idx_threads_session ON m_threads(session_id);

CREATE TABLE IF NOT EXISTS m_outbound_queue (
    intent_id      TEXT PRIMARY KEY,
    user_id        TEXT NOT NULL,
    agent          TEXT NOT NULL,
    thread_id      TEXT,
    content        TEXT NOT NULL,
    context_hint   TEXT NOT NULL,
    urgency        TEXT NOT NULL,
    triggered_by   TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    delivered_at   TEXT,
    delivery_state TEXT NOT NULL DEFAULT 'pending'
);
CREATE INDEX IF NOT EXISTS idx_outbound_state ON m_outbound_queue(delivery_state);

CREATE TABLE IF NOT EXISTS m_outbound_delivery_per_device (
    intent_id    TEXT NOT NULL,
    device_id    TEXT NOT NULL,
    sent_at      TEXT,
    received_at  TEXT,
    read_at      TEXT,
    PRIMARY KEY (intent_id, device_id)
);

CREATE TABLE IF NOT EXISTS m_push_subscriptions (
    subscription_id TEXT PRIMARY KEY,
    device_id       TEXT NOT NULL,
    endpoint        TEXT NOT NULL,
    p256dh_key      TEXT NOT NULL,
    auth_secret     TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    last_used_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_push_device ON m_push_subscriptions(device_id);

CREATE TABLE IF NOT EXISTS m_message_idempotency (
    client_msg_id  TEXT PRIMARY KEY,
    thread_id      TEXT NOT NULL,
    device_id      TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    response_cache TEXT
);
"""


class MessengerStore:
    """File-backed SQLite store for messenger substrate.

    Same connection-per-call pattern as ConversationStore. Thread-safe
    via SQLite's own locking; no in-memory connection pool needed at v1.
    """

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as con:
            con.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.db_path))
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        return con

    def list_tables(self) -> list[str]:
        with self._conn() as con:
            rows = con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        return [r["name"] for r in rows]

    def column_names(self, table: str) -> list[str]:
        with self._conn() as con:
            rows = con.execute(f"PRAGMA table_info({table})").fetchall()
        return [r["name"] for r in rows]

    def idempotency_lookup_or_record(
        self, *, client_msg_id: str, thread_id: str, device_id: str,
    ) -> dict | None:
        """Returns None if this is the first time we've seen client_msg_id
        (the caller should proceed). Returns the cached response dict if we've
        seen it before (the caller should return the cached value without
        re-processing)."""
        import json as _json
        from datetime import datetime as _dt, timezone as _tz
        with self._conn() as con:
            row = con.execute(
                "SELECT response_cache FROM m_message_idempotency WHERE client_msg_id=?",
                (client_msg_id,),
            ).fetchone()
            if row is not None:
                cached = row["response_cache"]
                return _json.loads(cached) if cached else {}
            con.execute(
                "INSERT INTO m_message_idempotency "
                "(client_msg_id, thread_id, device_id, created_at) "
                "VALUES (?, ?, ?, ?)",
                (client_msg_id, thread_id, device_id,
                 _dt.now(_tz.utc).isoformat()),
            )
        return None

    def idempotency_set_response(
        self, *, client_msg_id: str, response: dict,
    ) -> None:
        """Store the response for a previously-recorded client_msg_id so a
        retry hits the cache instead of re-processing."""
        import json as _json
        with self._conn() as con:
            con.execute(
                "UPDATE m_message_idempotency SET response_cache=? "
                "WHERE client_msg_id=?",
                (_json.dumps(response), client_msg_id),
            )
