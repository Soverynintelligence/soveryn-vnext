"""API for locally imported botdirectory charters (review only)."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify

from soveryn.platform.botdirectory.store import get_import, list_imports

bp = Blueprint("api_botdirectory", __name__)


def _data_root():
    try:
        env = current_app.extensions.get("soveryn", {}).get("env")
        if env is not None and getattr(env, "data_root", None):
            return env.data_root
    except Exception:
        pass
    return None


@bp.get("/api/botdirectory/imports")
def api_botdirectory_imports_list():
    """List charters Eve/Kernel imported for Jon's review."""
    items = list_imports(data_root=_data_root(), limit=200)
    return jsonify({
        "ok": True,
        "count": len(items),
        "imports": items,
        "scheduled": False,
        "note": (
            "These are job/role charters from botdirectory.ai — recipes for "
            "specialist bots, not running processes. Nothing here is live."
        ),
    }), 200


@bp.get("/api/botdirectory/imports/<slug>")
def api_botdirectory_imports_get(slug: str):
    """Full imported charter including prompt text."""
    try:
        data = get_import(slug, data_root=_data_root())
    except FileNotFoundError as e:
        return jsonify({"ok": False, "error": "not_found", "message": str(e)}), 404
    except ValueError as e:
        return jsonify({"ok": False, "error": "bad_slug", "message": str(e)}), 400
    return jsonify(data), 200
