"""StagedStore — SQLite store for staged X posts, one pending slot PER AGENT.

Keyed on `agent`, not `session_id`. Aetheria may propose a post during a
heartbeat wake (session `[heartbeat] aetheria`) but Jon's approval lands in
his PRIMARY chat thread — a different session id entirely. Keying on session
would never let the two sides match up, so the single "waiting for Jon"
slot lives per-agent instead. There is no session_id anywhere in this module.

Mirrors the connection style of the sibling `candidate_store.CandidateStore`.
No wall-clock calls happen inside this module — `stage` and `expire_stale`
take `now` as an explicit ISO-timestamp argument so callers (and tests) stay
deterministic. The staged post id is likewise derived deterministically from
`agent` + `now` + `text` (a hash), never randomly generated.
"""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional


@dataclass(frozen=True)
class StagedPost:
    """A post staged for Jon's approval before it goes out on X.

    Attributes:
        id: Deterministic id derived from agent + proposed_at + text.
        agent: The agent that proposed this post (e.g. "aetheria").
        text: The post content.
        reply_to: Tweet id this replies to, or None for an original post.
        proposed_at: ISO timestamp when the post was staged.
        state: One of "proposed", "published", "rejected", "expired".
    """

    id: str
    agent: str
    text: str
    reply_to: Optional[str]
    proposed_at: str
    state: str


class StagedBusyError(Exception):
    """Raised when staging a post while one is already proposed for that agent."""


DEFAULT_CONNECTION_TIMEOUT_SECONDS = 30.0


def _make_id(agent: str, now: str, text: str) -> str:
    """Deterministic id derived from agent + now + text (never random/uuid4)."""
    digest = hashlib.sha256(f"{agent}|{now}|{text}".encode("utf-8")).hexdigest()
    return digest[:16]


class StagedStore:
    """SQLite-backed store for staged X posts, one `proposed` slot per agent.

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
                CREATE TABLE IF NOT EXISTS staged_posts (
                    id TEXT PRIMARY KEY,
                    agent TEXT NOT NULL,
                    text TEXT NOT NULL,
                    reply_to TEXT,
                    proposed_at TEXT NOT NULL,
                    state TEXT NOT NULL
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

    @staticmethod
    def _row_to_post(row: sqlite3.Row) -> StagedPost:
        return StagedPost(
            id=row["id"],
            agent=row["agent"],
            text=row["text"],
            reply_to=row["reply_to"],
            proposed_at=row["proposed_at"],
            state=row["state"],
        )

    def stage(
        self,
        *,
        agent: str,
        text: str,
        reply_to: Optional[str],
        now: str,
    ) -> StagedPost:
        """Stage a new post for `agent`, awaiting Jon's approval.

        Raises StagedBusyError if a `proposed` post already exists for this
        agent — only one pending slot per agent at a time.
        """
        if self.pending(agent) is not None:
            raise StagedBusyError(f"a post is already staged for agent {agent!r}")

        post = StagedPost(
            id=_make_id(agent, now, text),
            agent=agent,
            text=text,
            reply_to=reply_to,
            proposed_at=now,
            state="proposed",
        )
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO staged_posts (id, agent, text, reply_to, proposed_at, state)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (post.id, post.agent, post.text, post.reply_to, post.proposed_at, post.state),
            )
        return post

    def pending(self, agent: str) -> Optional[StagedPost]:
        """Return the single `proposed` post for `agent`, or None."""
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id, agent, text, reply_to, proposed_at, state
                FROM staged_posts
                WHERE agent = ? AND state = 'proposed'
                ORDER BY proposed_at DESC
                LIMIT 1
                """,
                (agent,),
            ).fetchone()

        return self._row_to_post(row) if row is not None else None

    def pending_all(self) -> list[StagedPost]:
        """All `proposed` posts, any agent."""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, agent, text, reply_to, proposed_at, state
                FROM staged_posts
                WHERE state = 'proposed'
                ORDER BY proposed_at ASC
                """
            ).fetchall()
        return [self._row_to_post(row) for row in rows]

    def get(self, post_id: str) -> Optional[StagedPost]:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id, agent, text, reply_to, proposed_at, state
                FROM staged_posts
                WHERE id = ?
                """,
                (post_id,),
            ).fetchone()
        return self._row_to_post(row) if row is not None else None

    def mark(self, post_id: str, state: str) -> None:
        """Update a staged post's state."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE staged_posts SET state = ? WHERE id = ?",
                (state, post_id),
            )

    def expire_stale(self, now: str, ttl_hours: float) -> list[StagedPost]:
        """Flip any `proposed` post older than ttl_hours to `expired`.

        Compares `proposed_at` to `now` (both ISO timestamps). Returns the
        posts that were flipped so callers can note them.
        """
        now_dt = datetime.fromisoformat(now)

        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, agent, text, reply_to, proposed_at, state
                FROM staged_posts
                WHERE state = 'proposed'
                """
            ).fetchall()

            expired: list[StagedPost] = []
            for row in rows:
                proposed_dt = datetime.fromisoformat(row["proposed_at"])
                age_hours = (now_dt - proposed_dt).total_seconds() / 3600.0
                if age_hours > ttl_hours:
                    conn.execute(
                        "UPDATE staged_posts SET state = 'expired' WHERE id = ?",
                        (row["id"],),
                    )
                    post = self._row_to_post(row)
                    expired.append(
                        StagedPost(
                            id=post.id,
                            agent=post.agent,
                            text=post.text,
                            reply_to=post.reply_to,
                            proposed_at=post.proposed_at,
                            state="expired",
                        )
                    )

        return expired
