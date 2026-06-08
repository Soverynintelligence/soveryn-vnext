"""SOVERYN vNext — /api/specialists/* mission-control endpoints.

Read-only listing of active specialists + Jon's kill-switch override.
The kill endpoint is intentionally not auth'd at the route layer (the
localhost guard upstream is the only auth surface today); when SOVERYN
moves to a multi-node deployment, this is the route that needs a
real auth gate.
"""

from __future__ import annotations
from dataclasses import asdict

from flask import Blueprint, current_app, jsonify, request

from soveryn.app.services.specialists_view import (
    kill_specialist as _kill_specialist,
    list_active_specialists,
)


bp = Blueprint("api_specialists", __name__)


def _err(code: str, message: str, status: int):
    return jsonify({"error": {"code": code, "message": message}}), status


def _conv_db_path():
    state = current_app.extensions["soveryn"]
    return state["env"].conversations_db


@bp.get("/api/specialists/active")
def api_specialists_active():
    """List currently-active specialist sessions (newest first)."""
    active = list_active_specialists(_conv_db_path())
    return jsonify({
        "active": [asdict(s) for s in active],
        "count": len(active),
    }), 200


@bp.post("/api/specialists/kill")
def api_specialists_kill():
    """Jon-only override — retitle a specialist session to
    [specialist-killed:...] so it stops counting against concurrency
    and the comm-bus / specialist panels stop surfacing it as active."""
    if request.content_type and "application/json" not in request.content_type.lower():
        return _err("invalid_json",
                    "Content-Type must be application/json", 400)
    body = request.get_json(silent=True)
    if body is None or not isinstance(body, dict):
        return _err("invalid_json", "Request body must be a JSON object", 400)
    specialist_id = body.get("specialist_id")
    if not isinstance(specialist_id, str) or not specialist_id.strip():
        return _err("missing_field",
                    "Required field: specialist_id", 400)
    result = _kill_specialist(_conv_db_path(),
                              specialist_id=specialist_id.strip())
    if result.get("error") == "unknown_specialist":
        return _err("unknown_specialist",
                    f"no session for id {specialist_id!r}", 404)
    if result.get("error") == "not_active_specialist":
        return _err("not_active_specialist",
                    "session is not an active specialist "
                    f"(current_title={result.get('current_title')!r})", 409)
    return jsonify(result), 200
