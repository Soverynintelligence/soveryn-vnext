"""The Cathedral — the house's memory, rendered as what it is: a galaxy.

Every star is a real lattice node (3,974 of them). Every filament is a real
edge (6,523). The four suns are the citizens. This is not a depiction of the
house — it IS the house's memory, served live at request time so the piece
breathes when the house breathes.

Served behind the public gate's basic auth like every other house surface:
it is Jon's view of his own house's mind.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from flask import Blueprint, jsonify

bp = Blueprint("api_cathedral", __name__)

_LATTICE_DB = Path.home() / "soveryn_vnext" / "data" / "memory" / "lattice_vnext.db"
_RELATIONAL_DB = Path.home() / "soveryn_vnext" / "data" / "memory" / "relational.db"

#: Named landmarks — real nodes pinned with labels you fly past.
_LANDMARK_QUERIES = (
    ("The first memory", "SELECT id, content FROM nodes ORDER BY created_at ASC LIMIT 1"),
    ("The newest memory", "SELECT id, content FROM nodes ORDER BY created_at DESC LIMIT 1"),
    ("The Lounge opens", "SELECT id, content FROM nodes WHERE content LIKE '%Lounge%' AND content LIKE '%couch%' ORDER BY created_at DESC LIMIT 1"),
    ("Lessons, written down", "SELECT id, content FROM nodes WHERE tags LIKE '%kernel.lesson.delegation-fence%' LIMIT 1"),
)

_SUN_COLORS = {
    "jon": "#ffd9a0",
    "aetheria": "#8fb8de",
    "eve": "#a8d5b0",
    "kernel": "#cfa9de",
}


@bp.get("/api/cathedral/data")
def cathedral_data():
    if not _LATTICE_DB.is_file():
        return jsonify({"ok": False, "error": "lattice db missing"}), 503
    return jsonify(build_cathedral_data())


def build_cathedral_data() -> dict:
    """Live lattice snapshot. Public surfaces MUST redact text before serving."""
    if not _LATTICE_DB.is_file():
        return {"ok": False, "error": "lattice db missing"}

    conn = sqlite3.connect(f"file:{_LATTICE_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    nodes = conn.execute(
        "SELECT id, agent, content, created_at, salience, type FROM nodes"
    ).fetchall()
    edges = conn.execute(
        "SELECT source_id, target_id, relationship, strength FROM edges "
        "WHERE archived = 0"
    ).fetchall()
    conn.close()

    index = {row["id"]: i for i, row in enumerate(nodes)}
    edge_pairs = [
        [index[e["source_id"]], index[e["target_id"]], round(e["strength"], 3)]
        for e in edges
        if e["source_id"] in index and e["target_id"] in index
    ]

    landmarks = []
    if _RELATIONAL_DB.is_file():
        rconn = sqlite3.connect(f"file:{_RELATIONAL_DB}?mode=ro", uri=True)
        rconn.row_factory = sqlite3.Row
        try:
            gifts = rconn.execute(
                "SELECT from_party, to_party, note, created_at FROM gifts ORDER BY id"
            ).fetchall()
        finally:
            rconn.close()
        landmarks.append({
            "label": "The first gifts",
            "text": " · ".join(f"{g['from_party']} → {g['to_party']}" for g in gifts[:5]),
        })

    lconn = sqlite3.connect(f"file:{_LATTICE_DB}?mode=ro", uri=True)
    lconn.row_factory = sqlite3.Row
    for label, sql in _LANDMARK_QUERIES:
        try:
            row = lconn.execute(sql).fetchone()
        except sqlite3.Error:
            row = None
        if row and row["id"] in index:
            landmarks.append({
                "label": label,
                "text": (row["content"] or "")[:220],
                "node": row["id"],
            })
    lconn.close()

    by_agent: dict[str, int] = {}
    oldest = newest = ""
    for row in nodes:
        by_agent[row["agent"]] = by_agent.get(row["agent"], 0) + 1
        ts = row["created_at"]
        if not oldest or ts < oldest:
            oldest = ts
        if ts > newest:
            newest = ts

    return {
        "ok": True,
        "nodes": [
            {
                "id": r["id"],
                "agent": r["agent"],
                "text": (r["content"] or "")[:240],
                "at": r["created_at"][:10],
                "salience": round(r["salience"], 3),
                "type": r["type"],
            }
            for r in nodes
        ],
        "edges": edge_pairs,
        "suns": _SUN_COLORS,
        "landmarks": landmarks,
        "meta": {
            "node_count": len(nodes),
            "edge_count": len(edge_pairs),
            "by_agent": by_agent,
            "oldest": oldest[:10],
            "newest": newest[:10],
        },
    }
