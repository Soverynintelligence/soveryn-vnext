"""SOVERYN vNext — Lattice graph adapter (nodes only this commit).

Path-injected SQLite store mirroring production lattice.db nodes table.
Edges, dream_log, contradiction_flags deferred to later commits.

Embeddings are stored as TEXT (JSON-encoded list[float]) — same format as
production. Generation goes through soveryn.inference.llama_server_client.embed()
so vNext has exactly one embedding code path.

Layer is validated on WRITE against {private, global, library}; reads accept
anything (production has legacy 'lattice' values).
"""

from __future__ import annotations
import json
import math
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator


# Layer constants — write-side enum
LAYER_PRIVATE = "private"
LAYER_GLOBAL = "global"
LAYER_LIBRARY = "library"
WRITE_LAYERS: frozenset[str] = frozenset({LAYER_PRIVATE, LAYER_GLOBAL, LAYER_LIBRARY})

# Intensity tiers (parallel to production)
INTENSITY_DEFAULT = 0.3
INTENSITY_SIGNIFICANT = 0.7
INTENSITY_CORE = 1.0

DEFAULT_CONNECTION_TIMEOUT_SECONDS = 30.0
DEFAULT_KEYWORD_LIMIT = 20
DEFAULT_EMBED_LIMIT = 10
DEFAULT_EMBED_THRESHOLD = 0.70


class LatticeError(Exception):
    """Validation / state errors raised by the Lattice adapter."""


@dataclass(frozen=True)
class Node:
    id: str
    type: str
    layer: str
    agent: str
    content: str
    intensity: float
    salience: float
    access_count: int
    tags: tuple[str, ...]
    created_at: str
    updated_at: str
    embedding: tuple[float, ...] | None
    intent: str | None
    provenance: dict | None


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS nodes (
    id           TEXT PRIMARY KEY,
    type         TEXT NOT NULL,
    layer        TEXT NOT NULL DEFAULT 'lattice',
    agent        TEXT NOT NULL,
    content      TEXT NOT NULL,
    intensity    REAL NOT NULL DEFAULT 0.3,
    salience     REAL NOT NULL DEFAULT 0.5,
    access_count INTEGER NOT NULL DEFAULT 0,
    tags         TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    embedding    TEXT DEFAULT NULL,
    intent       TEXT,
    provenance   TEXT DEFAULT NULL
);

CREATE INDEX IF NOT EXISTS idx_nodes_agent    ON nodes(agent);
CREATE INDEX IF NOT EXISTS idx_nodes_layer    ON nodes(layer);
CREATE INDEX IF NOT EXISTS idx_nodes_type     ON nodes(type);
CREATE INDEX IF NOT EXISTS idx_nodes_salience ON nodes(salience DESC);
CREATE INDEX IF NOT EXISTS idx_nodes_created  ON nodes(created_at DESC);
"""


def _row_to_node(row: sqlite3.Row) -> Node:
    tags_raw = row["tags"]
    embedding_raw = row["embedding"]
    provenance_raw = row["provenance"]
    return Node(
        id=row["id"],
        type=row["type"],
        layer=row["layer"],
        agent=row["agent"],
        content=row["content"],
        intensity=float(row["intensity"]),
        salience=float(row["salience"]),
        access_count=int(row["access_count"]),
        tags=_safe_parse_tags(tags_raw),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        embedding=_safe_parse_embedding(embedding_raw),
        intent=row["intent"],
        provenance=_safe_parse_provenance(provenance_raw),
    )


def _safe_parse_embedding(raw: str | None) -> tuple[float, ...] | None:
    """Parse JSON-encoded embedding. Returns None on missing/malformed —
    callers (e.g. find_nodes_by_embedding) treat None as 'skip this row'.
    Production data can have corrupt or truncated JSON; the adapter
    tolerates it rather than crashing recall (Jon constraint 7)."""
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(parsed, list):
        return None
    try:
        return tuple(float(x) for x in parsed)
    except (TypeError, ValueError):
        return None


def _safe_parse_tags(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return ()
    if not isinstance(parsed, list):
        return ()
    return tuple(str(x) for x in parsed)


def _safe_parse_provenance(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class LatticeStore:
    """SQLite-backed Lattice. Path-injected; no module state."""

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

    # ─── Public API ──────────────────────────────────────────────────────────

    def write_node(
        self,
        agent: str,
        content: str,
        *,
        node_type: str = "fact",
        layer: str = LAYER_PRIVATE,
        intensity: float = INTENSITY_DEFAULT,
        tags: tuple[str, ...] | None = None,
        embedding: tuple[float, ...] | None = None,
        intent: str | None = None,
        provenance: dict | None = None,
    ) -> str:
        """Write a node. Returns node id. Validates layer on write (Jon constraint 4)."""
        if layer not in WRITE_LAYERS:
            raise LatticeError(
                f"layer={layer!r} not in {sorted(WRITE_LAYERS)}; "
                "legacy values are read-only"
            )
        if not (0.0 <= intensity <= 1.0):
            raise LatticeError(f"intensity={intensity} must be in [0.0, 1.0]")

        node_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        tags_json = json.dumps(list(tags or ()))
        embedding_json = json.dumps(list(embedding)) if embedding is not None else None
        provenance_json = json.dumps(provenance) if provenance is not None else None
        # salience seeded equal to intensity at write time (read-only thereafter for now)
        salience = round(intensity, 4)

        with self._conn() as conn:
            conn.execute(
                "INSERT INTO nodes (id, type, layer, agent, content, intensity, salience, "
                "access_count, tags, created_at, updated_at, embedding, intent, provenance) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)",
                (node_id, node_type, layer, agent, content, intensity, salience,
                 tags_json, now, now, embedding_json, intent, provenance_json),
            )
        return node_id

    def get_node(self, node_id: str) -> Node | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        return _row_to_node(row) if row else None

    def find_nodes_by_keywords(
        self,
        agent: str,
        query: str,
        *,
        limit: int = DEFAULT_KEYWORD_LIMIT,
        include_global: bool = True,
    ) -> tuple[Node, ...]:
        """Case-insensitive LIKE over content/tags. Ordered salience DESC, updated_at DESC.

        Returns this agent's private/legacy rows + (optionally) global rows.
        Library rows excluded (use find_nodes_by_embedding with layer_filter='library').
        """
        like = f"%{query.lower()}%"
        with self._conn() as conn:
            if include_global:
                rows = conn.execute(
                    "SELECT * FROM nodes "
                    "WHERE ((agent = ? AND layer != ?) OR layer = ?) "
                    "  AND layer != ? "
                    "  AND (LOWER(content) LIKE ? OR LOWER(IFNULL(tags, '')) LIKE ?) "
                    "ORDER BY salience DESC, updated_at DESC LIMIT ?",
                    (agent, LAYER_GLOBAL, LAYER_GLOBAL, LAYER_LIBRARY, like, like, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM nodes "
                    "WHERE agent = ? AND layer != ? AND layer != ? "
                    "  AND (LOWER(content) LIKE ? OR LOWER(IFNULL(tags, '')) LIKE ?) "
                    "ORDER BY salience DESC, updated_at DESC LIMIT ?",
                    (agent, LAYER_GLOBAL, LAYER_LIBRARY, like, like, limit),
                ).fetchall()
        return tuple(_row_to_node(r) for r in rows)

    def find_nodes_by_embedding(
        self,
        agent: str,
        embedding: tuple[float, ...],
        *,
        limit: int = DEFAULT_EMBED_LIMIT,
        threshold: float = DEFAULT_EMBED_THRESHOLD,
        layer_filter: str | None = None,
    ) -> tuple[tuple[Node, float], ...]:
        """Cosine-similarity search. Returns ((node, score), ...) ordered score DESC.

        - Rows with NULL embedding are skipped (Jon constraint 7).
        - `layer_filter=None` → this agent's private/legacy + global, library excluded.
        - `layer_filter='library'` → ONLY library rows (RAG path).
        - `layer_filter` other → that layer only.
        """
        with self._conn() as conn:
            if layer_filter is None:
                rows = conn.execute(
                    "SELECT * FROM nodes "
                    "WHERE embedding IS NOT NULL "
                    "  AND ((agent = ? AND layer != ?) OR layer = ?) "
                    "  AND layer != ? "
                    "ORDER BY salience DESC LIMIT 2000",
                    (agent, LAYER_GLOBAL, LAYER_GLOBAL, LAYER_LIBRARY),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM nodes "
                    "WHERE embedding IS NOT NULL AND layer = ? "
                    "ORDER BY salience DESC LIMIT 2000",
                    (layer_filter,),
                ).fetchall()

        scored: list[tuple[Node, float]] = []
        for r in rows:
            node = _row_to_node(r)
            if node.embedding is None:
                continue
            score = _cosine(embedding, node.embedding)
            if score >= threshold:
                scored.append((node, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return tuple(scored[:limit])


def embed_text(text: str) -> tuple[float, ...]:
    """Convenience: encode a single string via the embeddings server.

    Imports the client lazily so importing soveryn.memory.lattice doesn't
    drag in urllib at module load time.
    """
    from soveryn.inference.llama_server_client import EmbeddingRequest, embed
    resp = embed(EmbeddingRequest(input=(text,)))
    if not resp.vectors:
        raise LatticeError("embed_text: server returned no vectors")
    return resp.vectors[0]
