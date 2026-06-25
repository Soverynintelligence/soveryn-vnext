"""SOVERYN vNext — /api/cognition/* read surface for Mission Control.

Read endpoints (Phase 4.1 — read surface only; control/diff/drift-audit later):
- GET /api/cognition/note          — current sense-of-us note content + id
- GET /api/cognition/reflections   — recent reflection memories, newest-first
                                     optional ?limit=N (default 20)

Spec: docs/superpowers/specs/2026-06-22-continuous-cognition-design.md
      (Mission Control "Cognition" view section)
"""

from __future__ import annotations

from flask import Blueprint, abort, current_app, jsonify, request


bp = Blueprint("api_cognition", __name__)


def _state():
    return current_app.extensions["soveryn"]


def _cognition_store():
    store = _state().get("cognition_store")
    if store is None:
        abort(503, description="cognition_store not initialized")
    return store


@bp.get("/api/cognition/note")
def api_cognition_note():
    """Return the current sense-of-us note content and its lattice node id.

    Returns {"content": "", "id": null} when no note has been written yet —
    never a 404 or 500. The UI reads this to show the note that is currently
    shaping Aetheria's manner.
    """
    store = _cognition_store()
    content = store.current_note() or ""
    note_id = store.current_note_id()
    return jsonify({"content": content, "id": note_id}), 200


@bp.get("/api/cognition/reflections")
def api_cognition_reflections():
    """Return recent reflection memories, newest-first.

    Query params:
      limit  (int, default 20) — maximum number of items to return.

    Each item: {id, text, scope, citations, jon_originated, created_at}.
    """
    try:
        limit = int(request.args.get("limit", 20))
    except (TypeError, ValueError):
        limit = 20

    store = _cognition_store()
    # list_reflections() returns oldest-first; reverse for newest-first.
    reflections = list(reversed(store.list_reflections()))
    if limit > 0:
        reflections = reflections[:limit]

    return jsonify([
        {
            "id": r.id,
            "text": r.text,
            "scope": r.scope,
            "citations": list(r.citations),
            "jon_originated": r.jon_originated,
            "created_at": r.created_at,
        }
        for r in reflections
    ]), 200
