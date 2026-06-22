"""SOVERYN vNext — legacy UI compatibility bridge.

After the vNext-native UI landed, the legacy bridge moved from / to
/legacy. The vNext-native UI now occupies /. The legacy UI is still
reachable at /legacy (desktop) and /legacy/mobile (mobile) as a
fallback during any validation period.

Behavior:
  GET /legacy        → desktop_v2.html (raw HTML, no template rendering)
  GET /legacy/mobile → mobile_v3.html
  GET /ui/source     → JSON describing which file is being served and the
                       `_temporary: true` flag so the situation is obvious.

The bridge reads from `app.config["SOVERYN_LEGACY_TEMPLATES_DIR"]`
(default `~/soveryn_vnext/data/templates_legacy`; the original
soveryn_complete/templates tree was archived 2026-06-22). If the
expected file is missing, returns JSON 503 with code `ui_unavailable` —
never a Flask stack trace.

No static asset proxying. Relative `/static/...` references from the
HTML may 404 against vNext; that's useful signal about which assets
vNext would need to mirror if/when a real UI lands.

Every served template carries `X-SOVERYN-UI-Source: legacy-template`
so it's obvious from response headers that this is the bridge, not a
vNext-native UI.
"""

from __future__ import annotations
from pathlib import Path

from flask import Blueprint, current_app, jsonify, make_response


bp = Blueprint("ui_compat", __name__)


DESKTOP_TEMPLATE = "desktop_v2.html"
MOBILE_TEMPLATE = "mobile_v3.html"
LEGACY_SOURCE_HEADER = "X-SOVERYN-UI-Source"
LEGACY_SOURCE_VALUE = "legacy-template"


def _err(code: str, message: str, status: int):
    return jsonify({"error": {"code": code, "message": message}}), status


def _serve_template(filename: str):
    """Read filename from the configured legacy dir and return as HTML response.

    503 + JSON error if the file is missing or unreadable.
    """
    base = Path(current_app.config["SOVERYN_LEGACY_TEMPLATES_DIR"])
    target = base / filename
    if not target.is_file():
        return _err(
            "ui_unavailable",
            f"legacy template {filename!r} not found at {base}; "
            "set app.config['SOVERYN_LEGACY_TEMPLATES_DIR'] to a directory "
            "that contains it, or accept that the UI is unavailable in vNext",
            503,
        )
    try:
        html = target.read_text(encoding="utf-8")
    except OSError as e:
        return _err(
            "ui_unavailable",
            f"failed to read legacy template {filename!r}: {type(e).__name__}: {e}",
            503,
        )
    resp = make_response(html, 200)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    resp.headers[LEGACY_SOURCE_HEADER] = LEGACY_SOURCE_VALUE
    return resp


@bp.get("/legacy")
def desktop():
    return _serve_template(DESKTOP_TEMPLATE)


@bp.get("/legacy/mobile")
def mobile():
    return _serve_template(MOBILE_TEMPLATE)


@bp.get("/ui/source")
def ui_source():
    """Metadata about the compat bridge."""
    base = Path(current_app.config["SOVERYN_LEGACY_TEMPLATES_DIR"])
    return jsonify({
        "_temporary": True,
        "_note": "TODO(vnext-ui): legacy template bridge, not the final vNext UI",
        "legacy_templates_dir": str(base),
        "templates": {
            "desktop": {
                "path": str(base / DESKTOP_TEMPLATE),
                "exists": (base / DESKTOP_TEMPLATE).is_file(),
            },
            "mobile": {
                "path": str(base / MOBILE_TEMPLATE),
                "exists": (base / MOBILE_TEMPLATE).is_file(),
            },
        },
    }), 200
