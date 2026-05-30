"""Durable Attic storage.

The Attic is Aetheria's private, non-canonical memory namespace. It stores raw
or uncertain material separately from the canonical Lattice tables.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from soveryn.platform.lattice.provenance import Provenance, ProvenanceClass
from soveryn.platform.lattice.types import Entry, Region

DEFAULT_ATTIC_DB_PATH = Path("/home/jon-deoliveira/soveryn_vnext/data/lattice/attic.db")
DEFAULT_CONNECTION_TIMEOUT_SECONDS = 30.0

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS attic_entries (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    metadata TEXT NOT NULL,
    provenance TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attic_links (
    attic_id TEXT NOT NULL,
    lattice_id TEXT NOT NULL,
    PRIMARY KEY (attic_id, lattice_id),
    FOREIGN KEY (attic_id) REFERENCES attic_entries(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_attic_content ON attic_entries(content);
CREATE INDEX IF NOT EXISTS idx_attic_links_lattice ON attic_links(lattice_id);
"""


@dataclass(frozen=True)
class AtticRecord:
    id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    linked_lattice_ids: tuple[str, ...] = ()
    provenance: Provenance | None = None
    created_at: str = ""


class AtticStore:
    """SQLite-backed private Attic store."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        timeout_seconds: float = DEFAULT_CONNECTION_TIMEOUT_SECONDS,
    ) -> None:
        self.db_path = Path(db_path) if db_path is not None else _default_attic_path()
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

    def append(
        self,
        content: str,
        metadata: dict[str, Any] | None = None,
        *,
        linked_lattice_ids: tuple[str, ...] = (),
        provenance: Provenance | None = None,
    ) -> AtticRecord:
        content = content.strip()
        if not content:
            raise ValueError("content must be non-empty")
        record_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        metadata_dict = dict(metadata or {})
        links = tuple(str(item) for item in linked_lattice_ids)
        checked_provenance = provenance or _default_raw_provenance(created_at)
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO attic_entries (id, content, metadata, provenance, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    record_id,
                    content,
                    _json_dump(metadata_dict),
                    _provenance_dump(checked_provenance),
                    created_at,
                ),
            )
            conn.executemany(
                "INSERT INTO attic_links (attic_id, lattice_id) VALUES (?, ?)",
                ((record_id, link) for link in links),
            )
        return AtticRecord(
            id=record_id,
            content=content,
            metadata=metadata_dict,
            linked_lattice_ids=links,
            provenance=checked_provenance,
            created_at=created_at,
        )

    def fetch(self, query: str, *, include_links_to: str | None = None) -> tuple[Entry, ...]:
        like = f"%{query.lower()}%"
        params: list[Any] = [like]
        sql = (
            "SELECT e.* FROM attic_entries e "
            "WHERE LOWER(e.content) LIKE ?"
        )
        if include_links_to is not None:
            sql += (
                " AND EXISTS (SELECT 1 FROM attic_links l "
                "WHERE l.attic_id = e.id AND l.lattice_id = ?)"
            )
            params.append(include_links_to)
        sql += " ORDER BY e.created_at ASC, e.id ASC"
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
            return tuple(_row_to_entry(conn, row) for row in rows)

    def get_record(self, attic_id: str) -> AtticRecord | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM attic_entries WHERE id = ?", (attic_id,)).fetchone()
            return _row_to_record(conn, row) if row else None

    def records_linked_to(self, lattice_id: str) -> tuple[AtticRecord, ...]:
        """Return Attic records linked to a legacy/canonical lattice id."""

        with self._conn() as conn:
            rows = conn.execute(
                "SELECT e.* FROM attic_entries e "
                "JOIN attic_links l ON l.attic_id = e.id "
                "WHERE l.lattice_id = ? "
                "ORDER BY e.created_at ASC, e.id ASC",
                (str(lattice_id),),
            ).fetchall()
            return tuple(_row_to_record(conn, row) for row in rows)

    def promote(
        self,
        attic_id: str,
        *,
        lattice_store,
        to_region: Region,
        trigger: str | None,
        agent: str = "aetheria",
        corroboration_count: int = 0,
        corroboration_threshold: int = 2,
    ) -> str:
        record = self.get_record(attic_id)
        if record is None:
            raise ValueError(f"attic entry not found: {attic_id}")
        normalized_region = to_region if isinstance(to_region, Region) else Region(str(to_region))
        if normalized_region is Region.UNKNOWN:
            raise ValueError("to_region must be a canonical region")
        trigger_metadata = _validate_promotion_trigger(
            trigger,
            corroboration_count=corroboration_count,
            corroboration_threshold=corroboration_threshold,
        )
        promoted_at = datetime.now(timezone.utc).isoformat()
        provenance = Provenance(
            ProvenanceClass.CONSOLIDATED,
            source="attic_promotion",
            confidence=1.0 if trigger_metadata["trigger"] == "review" else 0.8,
            temporal_context=promoted_at,
            generator="AtticStore.promote",
            chain=(record.id,),
        )
        provenance_dict = _provenance_to_dict(provenance)
        provenance_dict.update(trigger_metadata)
        provenance_dict["attic_id"] = record.id
        return lattice_store.write_node(
            agent,
            record.content,
            node_type=normalized_region.value,
            provenance=provenance_dict,
        )


def _row_to_entry(conn: sqlite3.Connection, row: sqlite3.Row) -> Entry:
    metadata = _json_load_dict(row["metadata"])
    links = tuple(
        str(item["lattice_id"])
        for item in conn.execute(
            "SELECT lattice_id FROM attic_links WHERE attic_id = ? ORDER BY lattice_id ASC",
            (row["id"],),
        ).fetchall()
    )
    entry_metadata = dict(metadata)
    entry_metadata.update({
        "canonical": False,
        "zone": "attic",
        "linked_lattice_ids": list(links),
        "created_at": row["created_at"],
    })
    return Entry(
        id=row["id"],
        content=row["content"],
        region=Region.UNKNOWN,
        source="attic",
        metadata=entry_metadata,
        private=True,
        provenance=_provenance_load(row["provenance"]),
    )


def _row_to_record(conn: sqlite3.Connection, row: sqlite3.Row) -> AtticRecord:
    links = tuple(
        str(item["lattice_id"])
        for item in conn.execute(
            "SELECT lattice_id FROM attic_links WHERE attic_id = ? ORDER BY lattice_id ASC",
            (row["id"],),
        ).fetchall()
    )
    return AtticRecord(
        id=row["id"],
        content=row["content"],
        metadata=_json_load_dict(row["metadata"]),
        linked_lattice_ids=links,
        provenance=_provenance_load(row["provenance"]),
        created_at=row["created_at"],
    )


def _validate_promotion_trigger(
    trigger: str | None,
    *,
    corroboration_count: int,
    corroboration_threshold: int,
) -> dict[str, Any]:
    normalized = (trigger or "").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized == "review":
        return {"trigger": "review"}
    if normalized == "corroboration":
        if corroboration_threshold < 1:
            raise ValueError("corroboration_threshold must be >= 1")
        if corroboration_count < corroboration_threshold:
            raise ValueError("corroboration trigger requires count meeting threshold")
        return {
            "trigger": "corroboration",
            "corroboration_count": corroboration_count,
            "corroboration_threshold": corroboration_threshold,
        }
    raise ValueError("trigger must be 'review' or threshold-satisfied 'corroboration'")


def _default_attic_path() -> Path:
    override = os.environ.get("SOVERYN_ATTIC_DB")
    return Path(override) if override else DEFAULT_ATTIC_DB_PATH


def _default_raw_provenance(created_at: str) -> Provenance:
    return Provenance(
        ProvenanceClass.TOLD,
        source="attic",
        confidence=0.2,
        temporal_context=created_at,
        generator="AtticStore.append",
    )


def _json_dump(value: dict[str, Any]) -> str:
    try:
        return json.dumps(value, sort_keys=True)
    except TypeError as exc:
        raise ValueError(f"metadata is not JSON-serializable: {exc}") from exc


def _json_load_dict(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _provenance_dump(provenance: Provenance) -> str:
    return json.dumps(_provenance_to_dict(provenance), sort_keys=True)


def _provenance_to_dict(provenance: Provenance) -> dict[str, Any]:
    return {
        "cls": provenance.cls.value,
        "source": provenance.source,
        "confidence": provenance.confidence,
        "temporal_context": provenance.temporal_context,
        "generator": provenance.generator,
        "chain": list(provenance.chain),
        "derived_from": list(provenance.derived_from),
    }


def _provenance_load(raw: str) -> Provenance:
    parsed = json.loads(raw)
    return Provenance(
        parsed["cls"],
        source=parsed["source"],
        confidence=float(parsed["confidence"]),
        temporal_context=parsed["temporal_context"],
        generator=parsed["generator"],
        chain=tuple(parsed.get("chain") or ()),
        derived_from=tuple(parsed.get("derived_from") or ()),
    )
