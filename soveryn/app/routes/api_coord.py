"""SOVERYN vNext — /api/coord/* read-only board surface for mission control.

Cheap SQLite reads of the coordination state. Returns counts per board
+ status + the top-3 most-recent non-archived nodes per board. The
mission control page polls this and renders the boards panel.
"""

from __future__ import annotations
import json
import sqlite3

from flask import Blueprint, current_app, jsonify


bp = Blueprint("api_coord", __name__)


def _state():
    return current_app.extensions["soveryn"]


@bp.get("/api/coord/summary")
def api_coord_summary():
    env = _state()["env"]
    lattice_db = str(env.lattice_db)
    out = {
        "signal":    {"open": 0, "top": []},
        "blueprint": {"open": 0, "refining": 0, "ready": 0, "top": []},
        "friction":  {"open": 0, "top": []},
    }
    try:
        with sqlite3.connect(lattice_db) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT id, agent, content, created_at, provenance "
                "FROM nodes WHERE type = 'coordination' "
                "ORDER BY created_at DESC"
            ).fetchall()
    except sqlite3.OperationalError:
        return jsonify(out), 200

    for r in rows:
        try:
            prov = json.loads(r["provenance"] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        board = (prov.get("board") or "").lower()
        status = prov.get("status") or ""
        if status == "Archived":
            continue
        if board not in out:
            continue
        bucket = out[board]
        if board == "blueprint":
            if status == "Open":
                bucket["open"] += 1
            elif status == "Refining":
                bucket["refining"] += 1
            elif status == "Ready":
                bucket["ready"] += 1
        else:
            if status == "Open":
                bucket["open"] += 1
        # Keep up to 3 most recent per board.
        if len(bucket["top"]) < 3:
            content = r["content"] or ""
            bucket["top"].append({
                "id": r["id"],
                "agent": r["agent"],
                "status": status,
                "owner": prov.get("owner"),
                "created_at": r["created_at"],
                "content_head": content.strip()[:140],
            })

    return jsonify(out), 200
