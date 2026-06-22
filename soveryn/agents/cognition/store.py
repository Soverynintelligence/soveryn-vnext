"""CognitionStore — lattice-backed storage for the manner-reflection pipeline.

Spec: docs/superpowers/specs/2026-06-22-continuous-cognition-design.md

Composes over the SAME lattice nodes table as CoordinationStore — type +
provenance-JSON pattern, no parallel tables.  Constructed with a lattice
db path (path-injected, no module state).

HARD WRITE-ISOLATION (the load-bearing guard)
---------------------------------------------
All inserts are routed through _write().  _write() REFUSES — raises
CognitionWriteError — if:
  (a) node_type is not in COGNITION_NODE_TYPES, OR
  (b) provenance["region"] is not COGNITION_REGION.

Both conditions are checked independently so neither can be bypassed.
This makes it architecturally impossible for this store to write
souls / persona / values — the worst case is one region="cognition" row.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from soveryn.agents.cognition.types import (
    COGNITION_NODE_TYPES,
    COGNITION_REFLECTION_NODE_TYPE,
    COGNITION_NOTE_NODE_TYPE,
    COGNITION_REGION,
    CandidateObservation,
    CognitionWriteError,
    NoteVersion,
    ReflectionMemory,
)

DEFAULT_CONNECTION_TIMEOUT_SECONDS = 30.0


class CognitionStore:
    """SQLite-backed cognition store.  Path-injected; no module state.

    Composes over the lattice nodes table (same as CoordinationStore).
    Only writes rows with types in COGNITION_NODE_TYPES and provenance
    region=COGNITION_REGION — enforced by the _write() guard.
    """

    def __init__(
        self,
        db_path: Path,
        timeout_seconds: float = DEFAULT_CONNECTION_TIMEOUT_SECONDS,
    ) -> None:
        self.db_path = Path(db_path)
        self.timeout_seconds = timeout_seconds

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

    # ─── Hard write-isolation guard ──────────────────────────────────────────

    def _write(
        self,
        *,
        node_type: str,
        content: str,
        provenance: dict,
    ) -> str:
        """Insert one node into the lattice.  ONLY call from public methods.

        REFUSES with CognitionWriteError if:
          (a) node_type is not in COGNITION_NODE_TYPES, OR
          (b) provenance["region"] != COGNITION_REGION.

        Both conditions are checked independently.  Returns the new node id.
        """
        # Guard (a): type allowlist
        if node_type not in COGNITION_NODE_TYPES:
            raise CognitionWriteError(
                f"CognitionStore._write: node_type {node_type!r} is not in the "
                f"cognition allowlist {sorted(COGNITION_NODE_TYPES)!r}. "
                f"This store cannot write non-cognition node types."
            )
        # Guard (b): region constraint
        if provenance.get("region") != COGNITION_REGION:
            raise CognitionWriteError(
                f"CognitionStore._write: provenance['region'] must be "
                f"{COGNITION_REGION!r}; got {provenance.get('region')!r}. "
                f"This store cannot write to non-cognition lattice regions."
            )

        node_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO nodes "
                "(id, type, layer, agent, content, intensity, salience, "
                "access_count, tags, created_at, updated_at, embedding, "
                "intent, provenance) "
                "VALUES (?, ?, 'lattice', 'cognition_pipeline', ?, "
                "0.5, 0.5, 0, NULL, ?, ?, NULL, NULL, ?)",
                (
                    node_id,
                    node_type,
                    content,
                    now,
                    now,
                    json.dumps(provenance, sort_keys=True),
                ),
            )
        return node_id

    # ─── Reflection writes ───────────────────────────────────────────────────

    def write_reflection(self, obs: CandidateObservation) -> ReflectionMemory:
        """Persist a CandidateObservation as a ReflectionMemory.

        Provenance carries: region, scope, citations (list), jon_originated.
        All writes go through _write — isolation is enforced end-to-end.
        """
        provenance = {
            "region": COGNITION_REGION,
            "scope": obs.scope,
            "citations": list(obs.citations),
            "jon_originated": obs.jon_originated,
        }
        mem_id = self._write(
            node_type=COGNITION_REFLECTION_NODE_TYPE,
            content=obs.text,
            provenance=provenance,
        )
        # Re-read the created_at we wrote so the returned object is canonical.
        with self._conn() as conn:
            row = conn.execute(
                "SELECT created_at FROM nodes WHERE id = ?", (mem_id,)
            ).fetchone()
        return ReflectionMemory(
            id=mem_id,
            text=obs.text,
            scope=obs.scope,
            citations=obs.citations,
            jon_originated=obs.jon_originated,
            created_at=row["created_at"],
        )

    def list_reflections(self) -> list[ReflectionMemory]:
        """Return all persisted reflection memories, oldest first."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, content, provenance, created_at FROM nodes "
                "WHERE type = ? ORDER BY created_at ASC",
                (COGNITION_REFLECTION_NODE_TYPE,),
            ).fetchall()
        results: list[ReflectionMemory] = []
        for row in rows:
            prov = json.loads(row["provenance"] or "{}")
            results.append(ReflectionMemory(
                id=row["id"],
                text=row["content"],
                scope=prov.get("scope", "unsure"),
                citations=tuple(prov.get("citations") or []),
                jon_originated=bool(prov.get("jon_originated", False)),
                created_at=row["created_at"],
            ))
        return results

    # ─── Note version writes ─────────────────────────────────────────────────

    def write_note_version(
        self,
        content: str,
        supersedes: str | None = None,
    ) -> NoteVersion:
        """Persist a new version of the sense-of-us note.

        Each call creates a new NoteVersion row; old versions are retained.
        current_note() returns the content of the most-recently written version.
        """
        provenance: dict = {"region": COGNITION_REGION}
        if supersedes is not None:
            provenance["supersedes"] = supersedes
        note_id = self._write(
            node_type=COGNITION_NOTE_NODE_TYPE,
            content=content,
            provenance=provenance,
        )
        with self._conn() as conn:
            row = conn.execute(
                "SELECT created_at FROM nodes WHERE id = ?", (note_id,)
            ).fetchone()
        return NoteVersion(
            id=note_id,
            content=content,
            created_at=row["created_at"],
            supersedes=supersedes,
        )

    def current_note(self) -> str | None:
        """Return the content of the most-recently written note version.

        Returns None if no note version has been written yet.
        Ordering uses created_at DESC — the last write wins.
        """
        with self._conn() as conn:
            row = conn.execute(
                "SELECT content FROM nodes WHERE type = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (COGNITION_NOTE_NODE_TYPE,),
            ).fetchone()
        if row is None:
            return None
        return row["content"]
