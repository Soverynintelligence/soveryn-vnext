"""SOVERYN vNext — native UI route.

Serves the single-page vNext UI at /. The HTML+CSS+JS lives in
soveryn/app/templates/vnext_ui.html — self-contained, no framework,
no static asset dependencies, reads everything from the existing
vNext REST API (/api/models, /sessions, /chat, /chat_stream, etc.).

This route replaces the legacy template bridge that previously sat
at /; the legacy bridge moved to /legacy.
"""

from __future__ import annotations
from pathlib import Path

from flask import Blueprint, jsonify, make_response

bp = Blueprint("ui", __name__)

VNEXT_UI_TEMPLATE = Path(__file__).parent.parent / "templates" / "vnext_ui.html"


@bp.get("/")
def vnext_ui():
    """Serve the single-page vNext UI."""
    if not VNEXT_UI_TEMPLATE.is_file():
        return jsonify({"error": {
            "code": "ui_unavailable",
            "message": f"vNext UI template missing at {VNEXT_UI_TEMPLATE}",
        }}), 500
    html = VNEXT_UI_TEMPLATE.read_text(encoding="utf-8")
    resp = make_response(html, 200)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    resp.headers["X-SOVERYN-UI-Source"] = "vnext-native"
    return resp
