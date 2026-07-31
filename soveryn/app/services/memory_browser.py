"""Read-only browse and search over the lattice.

Jon, 2026-07-30: "i should be able to see all memory... i should be able to see."

Before this, the only memory surfaces were aggregate: /api/memory/activity gave
counts, library_writes gave recent write events. You could see that she had
written 747 reflections. You could not read one. That is the same defect this
week kept producing — a write path with a thin or absent read path — applied to
the largest store in the system.

PRIVATE IS EXCLUDED BY DEFAULT, and the exclusion lives here rather than in the
route. 2,301 of 2,607 nodes are in the `private` layer; the taxonomy has that
layer deliberately. Jon owns the hardware and can read the SQLite file whenever
he likes, so this is a convention rather than a wall — but a convention nobody
exercises and a default view are different things, and he chose the former:
"private is private until it's surfaced." Callers must pass include_private=True
explicitly, and every response says which mode produced it so a UI cannot show
private content while implying it is showing everything.

No full-text index on purpose. The whole corpus is 1.58 MB and a LIKE scan
returns in 3.5 ms; FTS5 would add a virtual table, sync triggers and a rebuild
step to save three milliseconds. Revisit at ~100x the data.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Layers hidden unless explicitly requested.
PRIVATE_LAYERS: frozenset[str] = frozenset({"private"})

DEFAULT_LIMIT = 50
MAX_LIMIT = 300
PREVIEW_CHARS = 320


@dataclass(frozen=True)
class MemoryNode:
    id: str
    type: str
    layer: str
    agent: str
    preview: str
    content: str | None
    tags: tuple[str, ...]
    salience: float | None
    access_count: int | None
    created_at: str
    updated_at: str | None
    intent: str | None
    provenance: dict | None = None
    edges: tuple[dict[str, Any], ...] = field(default_factory=tuple)


def _tags(raw: Any) -> tuple[str, ...]:
    if not raw:
        return ()
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        return tuple(str(t) for t in parsed) if isinstance(parsed, (list, tuple)) else ()
    except (ValueError, TypeError):
        return ()


def _preview(content: str | None) -> str:
    collapsed = " ".join((content or "").split())
    return collapsed if len(collapsed) <= PREVIEW_CHARS else collapsed[:PREVIEW_CHARS] + "…"


def _connect(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def browse(
    db_path: Path,
    *,
    q: str = "",
    node_type: str = "",
    agent: str = "",
    tag: str = "",
    include_private: bool = False,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> dict[str, Any]:
    """Timeline of nodes, newest first, with optional filters.

    Returns previews rather than full content — a timeline of 2,607 nodes at
    606 chars each would be 1.6 MB of JSON for a view nobody reads in full.
    """
    limit = max(1, min(int(limit), MAX_LIMIT))
    offset = max(0, int(offset))

    where: list[str] = []
    params: list[Any] = []
    if not include_private:
        where.append(f"layer NOT IN ({','.join('?' * len(PRIVATE_LAYERS))})")
        params.extend(sorted(PRIVATE_LAYERS))
    if q:
        where.append("content LIKE ?")
        params.append(f"%{q}%")
    if node_type:
        where.append("type = ?")
        params.append(node_type)
    if agent:
        where.append("agent = ?")
        params.append(agent)
    if tag:
        where.append("tags LIKE ?")
        params.append(f'%"{tag}"%')
    clause = f"WHERE {' AND '.join(where)}" if where else ""

    if not Path(db_path).is_file():
        return {"nodes": [], "total": 0, "include_private": include_private,
                "error": "lattice not found"}
    try:
        with _connect(Path(db_path)) as con:
            total = con.execute(
                f"SELECT COUNT(*) FROM nodes {clause}", params
            ).fetchone()[0]
            rows = con.execute(
                "SELECT id, type, layer, agent, content, tags, salience, "
                "       access_count, created_at, updated_at, intent "
                f"FROM nodes {clause} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
    except sqlite3.Error as exc:
        return {"nodes": [], "total": 0, "include_private": include_private,
                "error": str(exc)}

    return {
        "nodes": [
            {
                "id": r["id"], "type": r["type"], "layer": r["layer"],
                "agent": r["agent"], "preview": _preview(r["content"]),
                "tags": list(_tags(r["tags"])), "salience": r["salience"],
                "access_count": r["access_count"], "created_at": r["created_at"],
                "intent": r["intent"],
            }
            for r in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
        # Always reported, so a UI can never show a filtered view while
        # implying it is showing everything.
        "include_private": include_private,
    }


def get_node(db_path: Path, node_id: str, *, include_private: bool = False) -> dict | None:
    """One node in full, with its edges — the drill-down from preview to evidence.

    Returns None when the node does not exist OR is private and private was not
    requested. Deliberately indistinguishable: a viewer defaulting to
    non-private should not be able to enumerate private node IDs by probing.
    """
    if not Path(db_path).is_file():
        return None
    try:
        with _connect(Path(db_path)) as con:
            r = con.execute(
                "SELECT id, type, layer, agent, content, tags, salience, "
                "       access_count, created_at, updated_at, intent, provenance "
                "FROM nodes WHERE id = ?", (node_id,),
            ).fetchone()
            if r is None:
                return None
            if not include_private and r["layer"] in PRIVATE_LAYERS:
                return None
            edges = con.execute(
                "SELECT e.relationship, e.strength, e.reinforcement_count, "
                "       e.created_at, e.source_id, e.target_id, "
                "       n.type AS other_type, n.layer AS other_layer, "
                "       n.agent AS other_agent, n.content AS other_content "
                "FROM edges e "
                "LEFT JOIN nodes n ON n.id = CASE WHEN e.source_id = ? "
                "                                 THEN e.target_id ELSE e.source_id END "
                "WHERE (e.source_id = ? OR e.target_id = ?) AND e.archived = 0 "
                "ORDER BY e.created_at DESC LIMIT 60",
                (node_id, node_id, node_id),
            ).fetchall()
    except sqlite3.Error:
        return None

    try:
        prov = json.loads(r["provenance"]) if r["provenance"] else None
    except (ValueError, TypeError):
        prov = None

    out_edges = []
    for e in edges:
        other_id = e["target_id"] if e["source_id"] == node_id else e["source_id"]
        # An edge into private memory is acknowledged but not opened: hiding the
        # link entirely would misrepresent the graph's shape.
        other_private = (e["other_layer"] in PRIVATE_LAYERS) and not include_private
        out_edges.append({
            "relationship": e["relationship"],
            "direction": "out" if e["source_id"] == node_id else "in",
            "other_id": other_id,
            "other_type": e["other_type"],
            "other_agent": e["other_agent"],
            "other_preview": "(private)" if other_private else _preview(e["other_content"]),
            "other_private": other_private,
            "strength": e["strength"],
            "reinforcement_count": e["reinforcement_count"],
            "created_at": e["created_at"],
        })

    return {
        "id": r["id"], "type": r["type"], "layer": r["layer"], "agent": r["agent"],
        "content": r["content"], "tags": list(_tags(r["tags"])),
        "salience": r["salience"], "access_count": r["access_count"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "intent": r["intent"], "provenance": prov,
        "edges": out_edges, "include_private": include_private,
    }


def facets(db_path: Path, *, include_private: bool = False) -> dict[str, Any]:
    """Counts by type and agent, for the filter chips."""
    if not Path(db_path).is_file():
        return {"types": [], "agents": [], "total": 0, "private_hidden": 0}
    clause = "" if include_private else \
        f"WHERE layer NOT IN ({','.join('?' * len(PRIVATE_LAYERS))})"
    params = [] if include_private else sorted(PRIVATE_LAYERS)
    try:
        with _connect(Path(db_path)) as con:
            types = [dict(r) for r in con.execute(
                f"SELECT type, COUNT(*) AS n FROM nodes {clause} "
                "GROUP BY type ORDER BY n DESC", params)]
            agents = [dict(r) for r in con.execute(
                f"SELECT agent, COUNT(*) AS n FROM nodes {clause} "
                "GROUP BY agent ORDER BY n DESC", params)]
            total = con.execute(
                f"SELECT COUNT(*) FROM nodes {clause}", params).fetchone()[0]
            hidden = 0 if include_private else con.execute(
                f"SELECT COUNT(*) FROM nodes WHERE layer IN "
                f"({','.join('?' * len(PRIVATE_LAYERS))})",
                sorted(PRIVATE_LAYERS)).fetchone()[0]
    except sqlite3.Error:
        return {"types": [], "agents": [], "total": 0, "private_hidden": 0}
    # private_hidden is surfaced so the UI can say "2,301 private nodes not
    # shown" rather than silently presenting a partial lattice as the whole.
    return {"types": types, "agents": agents, "total": total,
            "private_hidden": hidden, "include_private": include_private}
