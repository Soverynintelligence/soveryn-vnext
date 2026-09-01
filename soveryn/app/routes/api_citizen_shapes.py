"""GET/PUT citizen badge shapes (Grok-bot style picker)."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from soveryn.platform.citizen_shapes import catalog, load_shapes, set_shape

bp = Blueprint("api_citizen_shapes", __name__)


@bp.get("/api/citizen-shapes")
def api_citizen_shapes_get():
    return jsonify({
        "ok": True,
        "shapes": load_shapes(),
        "catalog": catalog(),
    }), 200


@bp.put("/api/citizen-shapes")
def api_citizen_shapes_put():
    body = request.get_json(silent=True) or {}
    agent = str(body.get("agent") or "").strip()
    shape = str(body.get("shape") or "").strip()
    try:
        saved = set_shape(agent, shape)
    except ValueError as exc:
        return jsonify({"ok": False, "error": "bad_request", "message": str(exc)}), 400
    return jsonify({"ok": True, **saved}), 200
