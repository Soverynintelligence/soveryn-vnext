"""Representation daemon writeback.

Persists Conclusion objects into the lattice as `type='conclusion'` nodes,
with `concluded_from` edges to any premises that resolve to real existing
node ids (synthetic turn:<session>:<idx> premises are recorded in provenance
as text only — no edge).

When a conclusion supersedes an old node the old node is tagged
`historical_snapshot`, a `supersedes` edge is written (new → old), and a
`representation_log` audit row is inserted — the LOUD traceable trail.

dry_run=True writes NOTHING: no node, edge, log, or tag. Returns a summary
dict only.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from typing import Callable, Sequence

from soveryn.platform.lattice.legacy import LatticeStore
from soveryn.agents.representation.parse import Conclusion, confidence_rank


def write_conclusions(
    lattice_store: LatticeStore,
    conclusions: Sequence[Conclusion],
    *,
    owner_agent: str,
    subject: str,
    run_id: str,
    embed_fn: Callable[[str], tuple[float, ...]] | None,
    dry_run: bool,
    supersedes: dict[int, str] | None = None,
) -> dict:
    """Write Conclusion objects to the lattice.

    Args:
        lattice_store: LatticeStore instance (path-injected).
        conclusions: sequence of Conclusion objects to persist.
        owner_agent: the agent credited for these nodes (e.g. 'aetheria').
        subject: who the conclusions are about (e.g. 'jon').
        run_id: caller-supplied run identifier for provenance tracing.
        embed_fn: optional callable (text -> tuple[float,...]) for embedding.
                  None → no embedding stored.
        dry_run: if True, nothing is written. Summary only.
        supersedes: optional {index_in_conclusions: old_node_id} mapping.
                    Conclusions at those indices replace the named old nodes.

    Returns:
        dict with keys: written, edges, superseded, dry_run.
    """
    supersedes = supersedes or {}
    written = 0
    edges_written = 0
    superseded = 0

    if dry_run:
        return {
            "written": 0,
            "edges": 0,
            "superseded": 0,
            "dry_run": True,
        }

    db_path = lattice_store.db_path

    for i, c in enumerate(conclusions):
        # Build provenance dict
        old_node_id = supersedes.get(i)
        prov = {
            "kind": "conclusion",
            "subject": subject,
            "premises": list(c.premises),
            "confidence": c.confidence,
            "confidence_rank": confidence_rank(c.confidence),
            "mode": c.mode,
            "run_id": run_id,
            "supersedes": old_node_id,
        }

        # Compute embedding (best-effort)
        embedding: tuple[float, ...] | None = None
        if embed_fn is not None:
            try:
                embedding = embed_fn(c.content)
            except Exception:
                embedding = None

        # Write the conclusion node
        new_node_id = lattice_store.write_node(
            agent=owner_agent,
            content=c.content,
            node_type="conclusion",
            layer="private",
            embedding=embedding,
            provenance=prov,
        )
        written += 1

        # Resolve premise edges — only for real existing node ids
        real_premises = _resolve_real_premises(db_path, c.premises)
        now = datetime.now().isoformat()
        for premise_id in real_premises:
            try:
                with sqlite3.connect(str(db_path)) as con:
                    con.execute(
                        "INSERT INTO edges (id, source_id, target_id, relationship, "
                        "strength, bidirectional, reinforcement_count, reinforced_at, "
                        "created_at) VALUES (?, ?, ?, 'concluded_from', 0.5, 0, "
                        "1, ?, ?)",
                        (str(uuid.uuid4()), new_node_id, premise_id, now, now),
                    )
                edges_written += 1
            except sqlite3.IntegrityError:
                # Already linked — skip silently
                pass

        # Loud supersede when this conclusion replaces an old node
        if old_node_id is not None:
            _supersede(db_path, old_node_id=old_node_id, new_node_id=new_node_id,
                       conclusion=c, run_id=run_id)
            superseded += 1

    return {
        "written": written,
        "edges": edges_written,
        "superseded": superseded,
        "dry_run": False,
    }


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _resolve_real_premises(db_path, premises: tuple[str, ...]) -> list[str]:
    """Return the subset of premise tokens that are real existing node ids.

    Synthetic turn:<session>:<idx> tokens will not match any row and are
    silently excluded — they're still recorded in provenance as text.
    """
    if not premises:
        return []
    placeholders = ",".join("?" for _ in premises)
    with sqlite3.connect(str(db_path)) as con:
        rows = con.execute(
            f"SELECT id FROM nodes WHERE id IN ({placeholders})",
            tuple(premises),
        ).fetchall()
    return [r[0] for r in rows]


def _supersede(
    db_path,
    *,
    old_node_id: str,
    new_node_id: str,
    conclusion: Conclusion,
    run_id: str,
) -> None:
    """Tag old node historical_snapshot, write supersedes edge, insert audit log row."""
    now = datetime.now().isoformat()

    with sqlite3.connect(str(db_path)) as con:
        # 1) Tag old node historical_snapshot
        row = con.execute(
            "SELECT tags, content, provenance FROM nodes WHERE id=?", (old_node_id,)
        ).fetchone()
        if row is None:
            return  # old node doesn't exist — skip gracefully

        tags_raw, old_content, old_prov_raw = row
        try:
            existing_tags: list = json.loads(tags_raw) if tags_raw else []
            if not isinstance(existing_tags, list):
                existing_tags = []
        except (json.JSONDecodeError, TypeError):
            existing_tags = []

        if "historical_snapshot" not in existing_tags:
            existing_tags.append("historical_snapshot")

        con.execute(
            "UPDATE nodes SET tags=?, updated_at=? WHERE id=?",
            (json.dumps(existing_tags), now, old_node_id),
        )

        # 2) Write supersedes edge (new → old)
        con.execute(
            "INSERT INTO edges (id, source_id, target_id, relationship, "
            "strength, bidirectional, reinforcement_count, reinforced_at, "
            "created_at) VALUES (?, ?, ?, 'supersedes', 1.0, 0, 1, ?, ?)",
            (str(uuid.uuid4()), new_node_id, old_node_id, now, now),
        )

        # 3) Extract old confidence from provenance if available
        confidence_from: str | None = None
        try:
            if old_prov_raw:
                old_prov = json.loads(old_prov_raw)
                if isinstance(old_prov, dict):
                    confidence_from = old_prov.get("confidence")
        except (json.JSONDecodeError, TypeError):
            pass

        old_content_head = (old_content or "")[:200] or None
        new_content_head = conclusion.content[:200]

        # 4) Insert representation_log row
        con.execute(
            "INSERT INTO representation_log "
            "(id, old_id, new_id, old_content_head, new_content_head, "
            "driving_premises, confidence_from, confidence_to, run_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                old_node_id,
                new_node_id,
                old_content_head,
                new_content_head,
                json.dumps(list(conclusion.premises)),
                confidence_from,
                conclusion.confidence,
                run_id,
                now,
            ),
        )
