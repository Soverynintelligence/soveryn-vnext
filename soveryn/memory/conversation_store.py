"""SOVERYN vNext — conversation store adapter.

Path-injected SQLite store mirroring production conversations.db schema
(soveryn_complete/soveryn_memory/conversations.db). Includes FTS5 virtual
table and triggers — production depends on these.

Path is injected per Jon constraint 2: no module-level DB connection.
Caller decides DB location (vNext default is conversations_vnext.db via
soveryn.config.loader; tests pass tmp_path).
"""

from __future__ import annotations
import re
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator


VALID_ROLES: frozenset[str] = frozenset({"user", "assistant", "system", "tool"})
DEFAULT_CONNECTION_TIMEOUT_SECONDS = 30.0

_THINK_BLOCK_RE = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)
_THINK_OPEN_RE = re.compile(r"<think>[\s\S]*", re.IGNORECASE)
_THINK_NAKED_RE = re.compile(r"\A(?:(?!<think>).)*?</think>\s*", re.IGNORECASE | re.DOTALL)
_THINK_CLOSE_RE = re.compile(r"</think>", re.IGNORECASE)


def _strip_think_markup(text: str) -> str:
    if not text:
        return text
    cleaned = _THINK_BLOCK_RE.sub("", text)
    cleaned = _THINK_OPEN_RE.sub("", cleaned)
    cleaned = _THINK_NAKED_RE.sub("", cleaned)
    cleaned = _THINK_CLOSE_RE.sub("", cleaned)
    return cleaned


class ConversationStoreError(Exception):
    """Raised on validation / state errors in the conversation store."""


@dataclass(frozen=True)
class Turn:
    session_id: str
    agent: str
    role: str
    content: str
    timestamp: str
    source: str = "direct"


@dataclass(frozen=True)
class Session:
    session_id: str
    agent: str
    title: str | None
    created_at: str
    updated_at: str


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS conversations (
    session_id TEXT NOT NULL,
    agent TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'direct'
);

CREATE TABLE IF NOT EXISTS conversation_meta (
    session_id TEXT PRIMARY KEY,
    agent TEXT NOT NULL,
    title TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_session ON conversations(session_id);
CREATE INDEX IF NOT EXISTS idx_conversations_agent_ts ON conversations(agent, timestamp);
CREATE INDEX IF NOT EXISTS idx_conversations_agent_role_ts ON conversations(agent, role, timestamp);

CREATE VIRTUAL TABLE IF NOT EXISTS conversations_fts USING fts5(
    content,
    session_id UNINDEXED,
    agent UNINDEXED,
    role UNINDEXED,
    timestamp UNINDEXED,
    content='conversations',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS conversations_ai AFTER INSERT ON conversations BEGIN
    INSERT INTO conversations_fts(rowid, content, session_id, agent, role, timestamp)
    VALUES (new.rowid, new.content, new.session_id, new.agent, new.role, new.timestamp);
END;

CREATE TRIGGER IF NOT EXISTS conversations_ad AFTER DELETE ON conversations BEGIN
    INSERT INTO conversations_fts(conversations_fts, rowid, content, session_id, agent, role, timestamp)
    VALUES ('delete', old.rowid, old.content, old.session_id, old.agent, old.role, old.timestamp);
END;

CREATE TRIGGER IF NOT EXISTS conversations_au AFTER UPDATE ON conversations BEGIN
    INSERT INTO conversations_fts(conversations_fts, rowid, content, session_id, agent, role, timestamp)
    VALUES ('delete', old.rowid, old.content, old.session_id, old.agent, old.role, old.timestamp);
    INSERT INTO conversations_fts(rowid, content, session_id, agent, role, timestamp)
    VALUES (new.rowid, new.content, new.session_id, new.agent, new.role, new.timestamp);
END;
"""


class ConversationStore:
    """SQLite-backed conversation persistence. Path-injected; no module state."""

    def __init__(self, db_path: Path, timeout_seconds: float = DEFAULT_CONNECTION_TIMEOUT_SECONDS) -> None:
        self.db_path = Path(db_path)
        self.timeout_seconds = timeout_seconds
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=self.timeout_seconds)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
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

    # ─── Public API (names match what production app.py imports) ─────────────

    def new_session(self, agent: str, title: str | None = None) -> str:
        """Create a session row in conversation_meta. Returns session_id."""
        session_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO conversation_meta (session_id, agent, title, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, agent, title, now, now),
            )
        return session_id

    def save_turn(self, session_id: str, agent: str, role: str, content: str,
                  source: str = "direct") -> None:
        """Append a turn. Validates role. Touches conversation_meta.updated_at."""
        if role not in VALID_ROLES:
            raise ConversationStoreError(
                f"role={role!r} not in {sorted(VALID_ROLES)}"
            )
        now = datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO conversations (session_id, agent, role, content, timestamp, source) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, agent, role, content, now, source),
            )
            conn.execute(
                "UPDATE conversation_meta SET updated_at = ? WHERE session_id = ?",
                (now, session_id),
            )

    def load_history(self, session_id: str) -> tuple[Turn, ...]:
        """Return all turns for a session in insertion order."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT session_id, agent, role, content, timestamp, source "
                "FROM conversations WHERE session_id = ? ORDER BY rowid ASC",
                (session_id,),
            ).fetchall()
        return tuple(Turn(**{**dict(r), "content": _strip_think_markup(str(r["content"]))}) for r in rows)

    def list_sessions(self, agent: str | None = None, limit: int = 100) -> tuple[Session, ...]:
        """Return sessions, newest first, optionally scoped to one agent."""
        with self._conn() as conn:
            if agent is None:
                rows = conn.execute(
                    "SELECT session_id, agent, title, created_at, updated_at "
                    "FROM conversation_meta ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT session_id, agent, title, created_at, updated_at "
                    "FROM conversation_meta WHERE agent = ? ORDER BY updated_at DESC LIMIT ?",
                    (agent, limit),
                ).fetchall()
        return tuple(Session(**dict(r)) for r in rows)

    def get_session(self, session_id: str) -> Session | None:
        """Return the session metadata, or None if no such session."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT session_id, agent, title, created_at, updated_at "
                "FROM conversation_meta WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return Session(**dict(row)) if row else None

    def delete_session(self, session_id: str) -> None:
        """Drop the session meta AND all turns. Cascading by hand (no FK between tables in production)."""
        with self._conn() as conn:
            conn.execute("DELETE FROM conversations WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM conversation_meta WHERE session_id = ?", (session_id,))

    def update_title(self, session_id: str, title: str) -> None:
        now = datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute(
                "UPDATE conversation_meta SET title = ?, updated_at = ? WHERE session_id = ?",
                (title, now, session_id),
            )
