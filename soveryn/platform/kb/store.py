"""turbovec-backed reference index + SQLite sidecar for chunk text.

Vectors live in IdMapIndex (TurboQuant 4-bit). Text/metadata live in SQLite.
Nothing here writes to lattice_vnext.db.
"""
from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from soveryn.platform.lattice.types import Entry, Region

BIT_WIDTH = 4

_CHUNKS_SQL = """
CREATE TABLE IF NOT EXISTS chunks (
    internal_id INTEGER PRIMARY KEY,
    chunk_id    TEXT NOT NULL UNIQUE,
    content     TEXT NOT NULL,
    source_path TEXT,
    metadata    TEXT NOT NULL DEFAULT '{}'
);
"""


def default_kb_dir(data_root: Path | None = None) -> Path:
    if data_root is not None:
        return Path(data_root) / "kb"
    raw = os.environ.get("SOVERYN_DATA_ROOT")
    if raw:
        return Path(raw) / "kb"
    from soveryn.config.loader import DEFAULT_DATA_ROOT

    return Path(DEFAULT_DATA_ROOT) / "kb"


@dataclass(frozen=True)
class KBHit:
    chunk_id: str
    score: float
    content: str
    source_path: str | None
    metadata: dict[str, Any]


class KBStore:
    """Thin adapter over turbovec.IdMapIndex + a chunks sqlite file."""

    def __init__(self, root: Path | None = None, *, bit_width: int = BIT_WIDTH) -> None:
        from turbovec import IdMapIndex

        self.root = Path(root) if root is not None else default_kb_dir()
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "turbovec.idx"
        self.db_path = self.root / "chunks.db"
        self.bit_width = bit_width
        self._init_db()
        if self.index_path.is_file():
            self._index = IdMapIndex.load(str(self.index_path))
        else:
            self._index = IdMapIndex(bit_width=bit_width)

    def _init_db(self) -> None:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(_CHUNKS_SQL)
            conn.commit()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def __len__(self) -> int:
        with self._conn() as conn:
            return int(conn.execute("SELECT COUNT(*) c FROM chunks").fetchone()["c"])

    def add(
        self,
        chunk_id: str,
        embedding: Iterable[float],
        content: str,
        *,
        source_path: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Insert or replace one chunk. Returns the uint64 turbovec id."""
        vec = np.asarray(list(embedding), dtype=np.float32)
        if vec.ndim != 1 or vec.size == 0:
            raise ValueError("embedding must be a 1-D non-empty vector")
        nrm = float(np.linalg.norm(vec))
        if nrm > 0:
            vec = vec / nrm
        meta_json = json.dumps(metadata or {}, sort_keys=True)
        with self._conn() as conn:
            existing = conn.execute(
                "SELECT internal_id FROM chunks WHERE chunk_id = ?", (chunk_id,)
            ).fetchone()
            if existing:
                internal = int(existing["internal_id"])
                self._index.remove(internal)
                conn.execute(
                    "UPDATE chunks SET content=?, source_path=?, metadata=? "
                    "WHERE chunk_id=?",
                    (content, source_path, meta_json, chunk_id),
                )
            else:
                conn.execute(
                    "INSERT INTO chunks (chunk_id, content, source_path, metadata) "
                    "VALUES (?, ?, ?, ?)",
                    (chunk_id, content, source_path, meta_json),
                )
                internal = int(
                    conn.execute(
                        "SELECT internal_id FROM chunks WHERE chunk_id = ?",
                        (chunk_id,),
                    ).fetchone()["internal_id"]
                )
            conn.commit()
        ids = np.asarray([internal], dtype=np.uint64)
        self._index.add_with_ids(vec.reshape(1, -1), ids)
        return internal

    def sync(self) -> Path:
        self._index.sync(str(self.index_path))
        return self.index_path

    def search(
        self,
        query_embedding: Iterable[float],
        *,
        k: int = 10,
        chunk_allowlist: list[str] | None = None,
    ) -> tuple[KBHit, ...]:
        if len(self) == 0:
            return ()
        q = np.asarray(list(query_embedding), dtype=np.float32)
        nrm = float(np.linalg.norm(q))
        if nrm > 0:
            q = q / nrm
        allow = None
        if chunk_allowlist is not None:
            if not chunk_allowlist:
                return ()
            with self._conn() as conn:
                placeholders = ",".join("?" * len(chunk_allowlist))
                rows = conn.execute(
                    f"SELECT internal_id FROM chunks WHERE chunk_id IN ({placeholders})",
                    chunk_allowlist,
                ).fetchall()
            if not rows:
                return ()
            allow = np.asarray([int(r["internal_id"]) for r in rows], dtype=np.uint64)
        scores, ids = self._index.search(q.reshape(1, -1), k, allowlist=allow)
        got_ids = [int(x) for x in ids[0].tolist()]
        got_scores = [float(x) for x in scores[0].tolist()]
        if not got_ids:
            return ()
        placeholders = ",".join("?" * len(got_ids))
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM chunks WHERE internal_id IN ({placeholders})",
                got_ids,
            ).fetchall()
        by_id = {int(r["internal_id"]): r for r in rows}
        hits: list[KBHit] = []
        for iid, score in zip(got_ids, got_scores):
            row = by_id.get(iid)
            if row is None:
                continue
            try:
                meta = json.loads(row["metadata"] or "{}")
            except json.JSONDecodeError:
                meta = {}
            if not isinstance(meta, dict):
                meta = {}
            hits.append(
                KBHit(
                    chunk_id=row["chunk_id"],
                    score=score,
                    content=row["content"],
                    source_path=row["source_path"],
                    metadata=meta,
                )
            )
        return tuple(hits)

    def as_entries(self, hits: Iterable[KBHit]) -> tuple[Entry, ...]:
        out: list[Entry] = []
        for hit in hits:
            out.append(
                Entry(
                    id=hit.chunk_id,
                    content=hit.content,
                    region=Region.SEMANTIC,
                    source="kb",
                    metadata={
                        "score": hit.score,
                        "source_path": hit.source_path,
                        **hit.metadata,
                    },
                    private=False,
                )
            )
        return tuple(out)
