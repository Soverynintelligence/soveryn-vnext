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

    def mark_thread_read(
        self, *, thread_id: str, device_id: str,
        up_to_intent_id: str | None = None,
    ) -> int:
        """Mark all outbound delivery_per_device rows for this device + thread
        as read_at=now.

        Scope (v1): "thread read" = all delivered intents whose `thread_id`
        matches this thread (or `thread_id IS NULL` — the default-thread
        case, resolved at delivery time). Per-message read state inside a
        thread is not modeled at v1; Aetheria's Q7 verdict is loop closure,
        not granular tracking.

        If `up_to_intent_id` is given, only marks intents created at or
        before that intent's `created_at` (caller-side cursor support;
        unused at v1 but reserved).

        Returns number of delivery rows updated.
        """
        from datetime import datetime as _dt, timezone as _tz
        now = _dt.now(_tz.utc).isoformat()
        with self._conn() as con:
            if up_to_intent_id is None:
                rows = con.execute(
                    """
                    UPDATE m_outbound_delivery_per_device
                    SET read_at = ?
                    WHERE device_id = ?
                      AND read_at IS NULL
                      AND intent_id IN (
                          SELECT intent_id FROM m_outbound_queue
                          WHERE delivery_state = 'delivered'
                            AND (thread_id = ? OR thread_id IS NULL)
                      )
                    """,
                    (now, device_id, thread_id),
                )
            else:
                rows = con.execute(
                    """
                    UPDATE m_outbound_delivery_per_device
                    SET read_at = ?
                    WHERE device_id = ?
                      AND read_at IS NULL
                      AND intent_id IN (
                          SELECT intent_id FROM m_outbound_queue
                          WHERE delivery_state = 'delivered'
                            AND (thread_id = ? OR thread_id IS NULL)
                            AND created_at <= (
                                SELECT created_at FROM m_outbound_queue
                                WHERE intent_id = ?
                            )
                      )
                    """,
                    (now, device_id, thread_id, up_to_intent_id),
                )
            return rows.rowcount

    def list_outbound_for_agent(
        self, *, agent: str, limit: int = 20,
    ) -> list[dict]:
        """Return recent outbound intents for an agent with delivery + read
        state aggregated across devices. Used by the `list_my_outbound`
        introspection tool (Aetheria's Q7 loop closure).
        """
        with self._conn() as con:
            rows = con.execute(
                """
                SELECT q.intent_id, q.thread_id, q.content, q.context_hint,
                       q.urgency, q.created_at, q.delivered_at,
                       q.delivery_state,
                       COUNT(d.device_id) AS device_count,
                       SUM(CASE WHEN d.read_at IS NOT NULL THEN 1 ELSE 0 END)
                           AS read_count
                FROM m_outbound_queue q
                LEFT JOIN m_outbound_delivery_per_device d USING (intent_id)
                WHERE q.agent = ?
                GROUP BY q.intent_id
                ORDER BY q.created_at DESC
                LIMIT ?
                """,
                (agent, limit),
            ).fetchall()
        return [
            {
                "intent_id": r["intent_id"],
                "thread_id": r["thread_id"],
                "content_preview": (r["content"] or "")[:140],
                "context_hint": r["context_hint"],
                "urgency": r["urgency"],
                "created_at": r["created_at"],
                "delivered_at": r["delivered_at"],
                "delivery_state": r["delivery_state"],
                "read_by_devices": int(r["read_count"] or 0),
                "delivered_to_devices": int(r["device_count"] or 0),
            }
            for r in rows
        ]
