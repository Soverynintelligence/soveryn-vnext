"""SOVERYN vNext — /api/system/* read-only system stats."""

from __future__ import annotations
from dataclasses import asdict

from flask import Blueprint, jsonify

from soveryn.app.services.gpu_stats import get_gpu_stats

bp = Blueprint("api_system", __name__)


@bp.get("/api/system/gpu")
def api_system_gpu():
    r = get_gpu_stats()
    return jsonify({
        "available": r.available,
        "message": r.message,
        "gpus": [asdict(g) for g in r.gpus],
        "fetched_at": r.fetched_at,
    }), 200
