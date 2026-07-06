"""SOVERYN vNext — document store.

SQLite-backed store for deliverable documents (reports, drafts) authored by
agents (Aetheria, Vett). Separate from the lattice/memory; mirrors the
connection-per-call pattern of soveryn.memory.conversation_store.

Path is injected; no module-level DB connection.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS documents (
    id          TEXT PRIMARY KEY,
    agent       TEXT NOT NULL,
    title       TEXT NOT NULL,
    format      TEXT NOT NULL DEFAULT 'markdown',
    content     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'draft',
    tags        TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_documents_agent      ON documents(agent);
CREATE INDEX IF NOT EXISTS idx_documents_updated_at ON documents(updated_at DESC);
"""

DEFAULT_CONNECTION_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True)
class Document:
    id: str
    agent: str
    title: str
    format: str
    content: str
    status: str
    tags: tuple[str, ...]
    created_at: str
    updated_at: str


def _row_to_document(row: sqlite3.Row) -> Document:
    raw_tags = row["tags"]
    if raw_tags is None:
        tags: tuple[str, ...] = ()
    else:
        tags = tuple(json.loads(raw_tags))
    return Document(
        id=row["id"],
        agent=row["agent"],
        title=row["title"],
        format=row["format"],
        content=row["content"],
        status=row["status"],
        tags=tags,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class DocumentStore:
    """SQLite-backed document persistence. Path-injected; no module state."""

    def __init__(
        self,
        db_path: Path | str,
        timeout_seconds: float = DEFAULT_CONNECTION_TIMEOUT_SECONDS,
    ) -> None:
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

    # ─── Public API ───────────────────────────────────────────────────────────

    def create_document(
        self,
        *,
        agent: str,
        title: str,
        content: str,
        format: str = "markdown",
        tags: list[str] | None = None,
    ) -> str:
        """Insert a new document row. Returns the new document id (uuid4)."""
        doc_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        tags_json: str | None = json.dumps(list(tags)) if tags is not None else None
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO documents (id, agent, title, format, content, status, tags, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'draft', ?, ?, ?)",
                (doc_id, agent, title, format, content, tags_json, now, now),
            )
        return doc_id

    def get_document(self, doc_id: str) -> Document | None:
        """Return the Document with the given id, or None if not found."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, agent, title, format, content, status, tags, created_at, updated_at "
                "FROM documents WHERE id = ?",
                (doc_id,),
            ).fetchone()
        return _row_to_document(row) if row else None

    def list_documents(
        self,
        *,
        agent: str | None = None,
        status: str | None = None,
    ) -> tuple[Document, ...]:
        """Return documents newest-first by updated_at; optional agent/status filters."""
        clauses: list[str] = []
        params: list[str] = []

        if agent is not None:
            clauses.append("agent = ?")
            params.append(agent)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            f"SELECT id, agent, title, format, content, status, tags, created_at, updated_at "
            f"FROM documents {where} ORDER BY updated_at DESC"
        )
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return tuple(_row_to_document(r) for r in rows)

    def update_document(
        self,
        doc_id: str,
        *,
        title: str | None = None,
        content: str | None = None,
        status: str | None = None,
        tags: list[str] | None = None,
    ) -> bool:
        """Update only the provided fields; bump updated_at. Returns True if a row was updated."""
        assignments: list[str] = []
        params: list[object] = []

        if title is not None:
            assignments.append("title = ?")
            params.append(title)
        if content is not None:
            assignments.append("content = ?")
            params.append(content)
        if status is not None:
            assignments.append("status = ?")
            params.append(status)
        if tags is not None:
            assignments.append("tags = ?")
            params.append(json.dumps(list(tags)))

        if not assignments:
            # Nothing to update; check existence to decide return value.
            with self._conn() as conn:
                row = conn.execute("SELECT id FROM documents WHERE id = ?", (doc_id,)).fetchone()
            return row is not None

        now = datetime.now().isoformat()
        assignments.append("updated_at = ?")
        params.append(now)
        params.append(doc_id)

        sql = f"UPDATE documents SET {', '.join(assignments)} WHERE id = ?"
        with self._conn() as conn:
            cur = conn.execute(sql, params)
        return cur.rowcount > 0

    def append_to_document(self, doc_id: str, text: str) -> bool:
        """Append text to the END of a document's content, with clean
        paragraph separation. Only the NEW text is passed — the caller never
        re-sends the whole body, so this works no matter how large the
        document already is. Returns True if the document existed.
        """
        doc = self.get_document(doc_id)
        if doc is None:
            return False
        addition = text.strip("\n")
        base = doc.content.rstrip()
        new_content = (base + "\n\n" + addition) if base else addition
        return self.update_document(doc_id, content=new_content)

    def replace_in_document(self, doc_id: str, old: str, new: str) -> str:
        """Replace the single occurrence of ``old`` with ``new`` in a
        document's content. Only the changed passage is passed. Returns a
        status: 'ok', 'missing' (no such document), 'not_present' (``old``
        not found), or 'ambiguous' (``old`` occurs more than once — the
        caller must supply more surrounding context to disambiguate).
        """
        doc = self.get_document(doc_id)
        if doc is None:
            return "missing"
        occurrences = doc.content.count(old)
        if occurrences == 0:
            return "not_present"
        if occurrences > 1:
            return "ambiguous"
        self.update_document(doc_id, content=doc.content.replace(old, new, 1))
        return "ok"
