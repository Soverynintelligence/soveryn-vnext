"""Dream output parser + DB writer.

Per Aetheria's note: the cognition surface emits natural-language
synthesis, NOT a JSON-schema-constrained structure. The parser is
best-effort: it pulls [node:ID] references out of the prose and
uses adjacency to suggest edges, while the synthesis prose itself
becomes the reflection node content.

DB writes go to three places (silent residue + accessible reflection):
  - nodes (layer='dream', type='reflection') ← reflection content
  - edges (relationship='dream_association') ← extracted from [node:ID] adjacency
  - dream_log ← audit row, always
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from soveryn.platform.lattice.legacy import LAYER_DREAM


# Matches [node:ID] where ID is any non-bracket, non-whitespace run.
# UUIDs (with dashes), short slugs, and numeric IDs all work.
_NODE_REF_PATTERN = re.compile(r"\[node:([^\]\s]+)\]")


def extract_node_references(text: str) -> list[str]:
    """Pull every [node:ID] reference from the text. Deduped, order-preserving."""
    if not isinstance(text, str):
        return []
    seen: list[str] = []
    seen_set: set[str] = set()
    for m in _NODE_REF_PATTERN.finditer(text):
        nid = m.group(1)
        if nid and nid not in seen_set:
            seen.append(nid)
            seen_set.add(nid)
    return seen


def extract_node_pairs(
    text: str, *, max_distance: int = 250,
) -> list[tuple[str, str]]:
    """Pair adjacent [node:ID] references within max_distance characters.

    Adjacency = "mentioned in the same neighborhood of prose." Crude but
    matches the natural-language structure: when a synthesis mentions two
    node IDs close together, they're being connected.
    """
    if not isinstance(text, str):
        return []
    matches = list(_NODE_REF_PATTERN.finditer(text))
    if len(matches) < 2:
        return []
    pairs: list[tuple[str, str]] = []
    for i in range(len(matches) - 1):
        a = matches[i]
        b = matches[i + 1]
        if (b.start() - a.end()) <= max_distance:
            pairs.append((a.group(1), b.group(1)))
    return pairs


def write_dream_outputs(
    lattice_db_path: Path,
    *,
    dream_run_id: str,
    synthesis: str,
    associations: str,
    contradictions: str,
    loop_health: float,
    nodes_read: int,
    is_dry_run: bool,
) -> None:
    """Persist the dream outputs. Dry-run skips reflection + edges + flags;
    the audit row goes in either way."""
    edges_created = 0
    contradictions_flagged = 0
    reflection_node_id: str | None = None

    if not is_dry_run and synthesis and synthesis.strip():
        reflection_node_id = _write_reflection_node(
            lattice_db_path,
            dream_run_id=dream_run_id,
            synthesis=synthesis,
            associations=associations,
            contradictions=contradictions,
        )
        edges_created = _write_edges_from_synthesis(
            lattice_db_path,
            synthesis=synthesis,
            reflection_node_id=reflection_node_id,
        )
        contradictions_flagged = _write_contradiction_flags(
            lattice_db_path,
            contradictions=contradictions,
            reflection_node_id=reflection_node_id,
        )

    _write_dream_log_row(
        lattice_db_path,
        dream_run_id=dream_run_id,
        synthesis=synthesis,
        loop_health=loop_health,
        nodes_read=nodes_read,
        edges_created=edges_created,
        contradictions_flagged=contradictions_flagged,
        is_dry_run=is_dry_run,
    )


def _write_reflection_node(
    lattice_db_path: Path,
    *,
    dream_run_id: str,
    synthesis: str,
    associations: str,
    contradictions: str,
) -> str:
    """Persist the synthesis as a layer='dream' node. Returns its id."""
    node_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    provenance = {
        "source": "dream_daemon",
        "dream_run_id": dream_run_id,
        "passes_visible": {
            "associations_len": len(associations or ""),
            "contradictions_len": len(contradictions or ""),
            "synthesis_len": len(synthesis or ""),
        },
    }
    with sqlite3.connect(str(lattice_db_path)) as con:
        con.execute(
            "INSERT INTO nodes (id, type, layer, agent, content, "
            "intensity, salience, access_count, created_at, updated_at, "
            "provenance) VALUES (?, 'reflection', ?, 'aetheria', ?, "
            "0.6, 0.6, 0, ?, ?, ?)",
            (node_id, LAYER_DREAM, synthesis.strip(), now, now,
             json.dumps(provenance, sort_keys=True)),
        )
    return node_id


def _write_edges_from_synthesis(
    lattice_db_path: Path,
    *,
    synthesis: str,
    reflection_node_id: str,
) -> int:
    """Extract [node:ID] adjacency pairs and write edges with
    relationship='dream_association'. Skips edges where either node id
    doesn't exist in the nodes table (best-effort tolerance)."""
    pairs = extract_node_pairs(synthesis)
    if not pairs:
        return 0
    now = datetime.now().isoformat()
    written = 0
    with sqlite3.connect(str(lattice_db_path)) as con:
        # Verify which referenced node ids actually exist; skip dangling refs
        all_refs = {ref for pair in pairs for ref in pair}
        if not all_refs:
            return 0
        placeholders = ",".join("?" for _ in all_refs)
        existing = {
            r[0] for r in con.execute(
                f"SELECT id FROM nodes WHERE id IN ({placeholders})",
                tuple(all_refs),
            ).fetchall()
        }
        for source_id, target_id in pairs:
            if source_id not in existing or target_id not in existing:
                continue
            try:
                con.execute(
                    "INSERT INTO edges (id, source_id, target_id, relationship, "
                    "strength, bidirectional, reinforcement_count, reinforced_at, "
                    "created_at) VALUES (?, ?, ?, 'dream_association', 0.5, 1, "
                    "1, ?, ?)",
                    (str(uuid.uuid4()), source_id, target_id, now, now),
                )
                written += 1
            except sqlite3.IntegrityError:
                # Same pair already linked — skip silently
                continue
    return written


def _write_contradiction_flags(
    lattice_db_path: Path,
    *,
    contradictions: str,
    reflection_node_id: str,
) -> int:
    """Extract [node:ID] adjacency pairs from the Pass 2 contradictions prose
    and write contradiction_flags rows. One row per pair.

    Skips pairs where either node id doesn't exist in the nodes table
    (best-effort tolerance — same policy as _write_edges_from_synthesis).
    Returns the count written.
    """
    pairs = extract_node_pairs(contradictions)
    if not pairs:
        return 0
    now = datetime.now().isoformat()
    written = 0
    with sqlite3.connect(str(lattice_db_path)) as con:
        all_refs = {ref for pair in pairs for ref in pair}
        placeholders = ",".join("?" for _ in all_refs)
        existing = {
            r[0] for r in con.execute(
                f"SELECT id FROM nodes WHERE id IN ({placeholders})",
                tuple(all_refs),
            ).fetchall()
        }
        for node_a_id, node_b_id in pairs:
            if node_a_id not in existing or node_b_id not in existing:
                continue
            try:
                con.execute(
                    "INSERT INTO contradiction_flags "
                    "(id, edge_id, node_a_id, node_b_id, flagged_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), reflection_node_id,
                     node_a_id, node_b_id, now),
                )
                written += 1
            except sqlite3.IntegrityError:
                continue
    return written


def _write_dream_log_row(
    lattice_db_path: Path,
    *,
    dream_run_id: str,
    synthesis: str,
    loop_health: float,
    nodes_read: int,
    edges_created: int,
    contradictions_flagged: int,
    is_dry_run: bool,
) -> None:
    summary = synthesis.strip()[:500] if synthesis else "(silent)"
    with sqlite3.connect(str(lattice_db_path)) as con:
        con.execute(
            "INSERT INTO dream_log "
            "(id, trigger, agent, nodes_read, edges_created, nodes_merged, "
            "contradictions_flagged, summary, ran_at, loop_health, dry_run) "
            "VALUES (?, 'quiet_hours', 'aetheria', ?, ?, 0, ?, ?, ?, ?, ?)",
            (dream_run_id, nodes_read, edges_created, contradictions_flagged,
             summary, datetime.now().isoformat(), loop_health,
             1 if is_dry_run else 0),
        )
