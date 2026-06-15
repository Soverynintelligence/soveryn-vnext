"""SOVERYN vNext — /api/coord/* board surface for mission control.

Read endpoints:
- GET  /api/coord/summary          — counts per board + top-3 most recent

Write endpoints (added 2026-06-15 to close the loop on Jon's side; Aetheria's
"Coordination Blackout" surfaced the gap that the board view was read-only,
so items piled up because Jon had no way to close them through the surface he
was looking at):
- POST /api/coord/<node_id>/status   — body {"status": "Open"|"Refining"|"Ready"}
- POST /api/coord/<node_id>/archive  — body {"lesson": "..."} (lesson required by store contract)

All write endpoints localhost-only — Mission Control is the local dashboard.
"""

from __future__ import annotations
import json
import sqlite3

from flask import Blueprint, abort, current_app, jsonify, request


bp = Blueprint("api_coord", __name__)


_LOCALHOST_ADDRS = {"127.0.0.1", "::1"}


def _require_localhost():
    if request.remote_addr not in _LOCALHOST_ADDRS:
        abort(403, description="coord write endpoints require localhost")


def _state():
    return current_app.extensions["soveryn"]


def _coord_store():
    store = _state().get("coord_store")
    if store is None:
        abort(503, description="coord_store not initialized")
    return store


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


@bp.post("/api/coord/<node_id>/status")
def api_coord_set_status(node_id: str):
    """Transition a coord node's status. Body: {"status": "Open"|"Refining"|"Ready"}.

    Mission Control calls this when Jon clicks the status pills on a board item.
    Archived transitions go through /archive (which requires a lesson)."""
    _require_localhost()
    from soveryn.platform.coordination.types import CoordStatus
    from soveryn.platform.coordination.store import CoordinationError

    body = request.get_json(silent=True) or {}
    raw_status = (body.get("status") or "").strip()
    if not raw_status:
        return jsonify({"error": "status field required"}), 400
    try:
        new_status = CoordStatus(raw_status)
    except ValueError:
        return jsonify({
            "error": f"unknown status {raw_status!r}",
            "allowed": [s.value for s in CoordStatus],
        }), 400

    store = _coord_store()
    try:
        node = store.update_status(node_id, new_status, acting_agent="jon")
    except CoordinationError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500
    return jsonify({
        "id": node.id,
        "status": node.status.value,
        "board": node.board.value,
    }), 200


@bp.post("/api/coord/<node_id>/archive")
def api_coord_archive(node_id: str):
    """Archive a coord node. Body: {"lesson": "..."} — non-empty lesson required.

    Archive != Delete. Per the store contract a paired Lesson Learned lattice
    node is written so the resolution becomes recallable memory; the coord node
    is marked Archived and linked to that lesson. The lesson text is whatever
    Jon types in the close-item dialog."""
    _require_localhost()
    from soveryn.platform.coordination.store import CoordinationError

    body = request.get_json(silent=True) or {}
    lesson = (body.get("lesson") or "").strip()
    if not lesson:
        return jsonify({"error": "lesson field required (non-empty)"}), 400

    store = _coord_store()
    try:
        node = store.archive_node(
            node_id,
            lesson_learned_content=lesson,
            acting_agent="jon",
        )
    except CoordinationError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500
    return jsonify({
        "id": node.id,
        "status": node.status.value,
        "archived_lesson_id": node.archived_lesson_id,
    }), 200
