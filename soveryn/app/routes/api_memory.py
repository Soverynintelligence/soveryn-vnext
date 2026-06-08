"""SOVERYN vNext — /api/memory/* read-only memory stats."""

from __future__ import annotations
from dataclasses import asdict

from flask import Blueprint, current_app, jsonify, request

from soveryn.app.services.memory_activity import (
    daily_write_counts, recent_library_writes, total_node_count,
)
from soveryn.memory.lattice import LatticeStore

bp = Blueprint("api_memory", __name__)

_MAX_DAYS = 90
_DEFAULT_DAYS = 14
_LIBRARY_FEED_DEFAULT_LIMIT = 12
_LIBRARY_FEED_MAX_LIMIT = 50


def _err(code: str, message: str, status: int):
    return jsonify({"error": {"code": code, "message": message}}), status


def _get_lattice_store() -> LatticeStore:
    """Resolve LatticeStore from app extensions, opening one if not cached."""
    state = current_app.extensions["soveryn"]
    store = state.get("lattice_store")
    if store is None:
        store = LatticeStore(state["env"].lattice_db)
        state["lattice_store"] = store
    return store


@bp.get("/api/memory/activity")
def api_memory_activity():
    raw = request.args.get("days", str(_DEFAULT_DAYS))
    try:
        days = int(raw)
    except ValueError:
        return _err("invalid_message", f"days must be an integer, got {raw!r}", 400)
    if days < 1:
        return _err("invalid_message", "days must be >= 1", 400)
    days = min(days, _MAX_DAYS)

    store = _get_lattice_store()
    activity = daily_write_counts(store, days=days)
    return jsonify({
        "days": activity.days,
        "buckets": [asdict(b) for b in activity.buckets],
        "total_nodes": total_node_count(store),
    }), 200


@bp.get("/api/memory/library_writes")
def api_memory_library_writes():
    """Recent library-layer writes (newest first) for the mission control feed.

    Surfaces type='library' nodes only — the deliberate synthesis writes
    Aetheria + the agents make, not document-chunk fragments. Default 12,
    max 50.
    """
    raw = request.args.get("limit", str(_LIBRARY_FEED_DEFAULT_LIMIT))
    try:
        limit = int(raw)
    except ValueError:
        return _err("invalid_message", f"limit must be an integer, got {raw!r}", 400)
    if limit < 1:
        return _err("invalid_message", "limit must be >= 1", 400)
    limit = min(limit, _LIBRARY_FEED_MAX_LIMIT)

    store = _get_lattice_store()
    writes = recent_library_writes(store, limit=limit)
    return jsonify({
        "limit": limit,
        "writes": [
            {
                "id": w.id,
                "agent": w.agent,
                "content_head": w.content_head,
                "created_at": w.created_at,
                "tags": list(w.tags),
            }
            for w in writes
        ],
    }), 200
