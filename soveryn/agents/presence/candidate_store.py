"""CandidateStore — SQLite store for tweet candidates with dedup, ranking, and posted-id ledger."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class Candidate:
    """A tweet candidate for posting.

    Attributes:
        tweet_id: Unique identifier for this candidate.
        author: Author/source of the candidate.
        text: The tweet content.
        url: Associated URL (or empty string).
        kind: Type of candidate ("topic", "mention", or "reply").
        score: Ranking score (higher = better).
        status: Current status (pending|drafted|awaiting_approval|posted|rejected|failed).
        created_at: ISO timestamp when the candidate was created.
    """
    tweet_id: str
    author: str
    text: str
    url: str
    kind: str
    score: float
    status: str
    created_at: str


DEFAULT_CONNECTION_TIMEOUT_SECONDS = 30.0


class CandidateStore:
    """SQLite-backed candidate store for tweet candidates.

    Maintains two tables:
    - candidates: stores candidate tweets with score and status for ranking/filtering.
    - posted_ids: ledger of tweet IDs we posted so they're never re-ingested.

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
                CREATE TABLE IF NOT EXISTS candidates (
                    tweet_id TEXT PRIMARY KEY,
                    author TEXT NOT NULL,
                    text TEXT NOT NULL,
                    url TEXT,
                    kind TEXT NOT NULL,
                    score REAL NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS posted_ids (
                    tweet_id TEXT PRIMARY KEY
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

    def is_seen(self, tweet_id: str) -> bool:
        """Check if a tweet ID has been seen (in either candidates or posted_ids).

        Returns True if the tweet_id exists in the candidates table OR the
        posted_ids table. This ensures our own posted tweets are never
        re-ingested as fresh mentions.
        """
        with self._conn() as conn:
            # Check candidates table
            row = conn.execute(
                "SELECT 1 FROM candidates WHERE tweet_id = ?",
                (tweet_id,),
            ).fetchone()
            if row is not None:
                return True

            # Check posted_ids table
            row = conn.execute(
                "SELECT 1 FROM posted_ids WHERE tweet_id = ?",
                (tweet_id,),
            ).fetchone()
            return row is not None

    def upsert(self, candidate: Candidate) -> None:
        """Insert a candidate, ignoring duplicates (by tweet_id).

        Uses INSERT OR IGNORE so duplicate tweet_ids are silently skipped.
        """
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO candidates
                (tweet_id, author, text, url, kind, score, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate.tweet_id,
                    candidate.author,
                    candidate.text,
                    candidate.url,
                    candidate.kind,
                    candidate.score,
                    candidate.status,
                    candidate.created_at,
                ),
            )

    def pending_ranked(self, limit: int) -> list[Candidate]:
        """Retrieve pending candidates ranked by score (descending).

        Returns up to `limit` candidates with status='pending', ordered by
        score DESC (highest score first).
        """
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT tweet_id, author, text, url, kind, score, status, created_at
                FROM candidates
                WHERE status = 'pending'
                ORDER BY score DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [
            Candidate(
                tweet_id=row["tweet_id"],
                author=row["author"],
                text=row["text"],
                url=row["url"],
                kind=row["kind"],
                score=row["score"],
                status=row["status"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def mark(self, tweet_id: str, status: str) -> None:
        """Update a candidate's status.

        Valid statuses: pending, drafted, awaiting_approval, posted, rejected, failed.
        """
        with self._conn() as conn:
            conn.execute(
                "UPDATE candidates SET status = ? WHERE tweet_id = ?",
                (status, tweet_id),
            )

    def record_posted_id(self, tweet_id: str) -> None:
        """Record a tweet ID as one WE posted.

        This marks the ID in the posted_ids table so it's never re-ingested
        as a fresh mention (is_seen will return True for it).
        """
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO posted_ids (tweet_id) VALUES (?)",
                (tweet_id,),
            )
