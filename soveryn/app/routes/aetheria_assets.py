"""Aetheria-asset serving routes.

Right now this serves generated images from ~/ComfyUI/output/ so the chat
UI can render them inline. Read-only; strict filename allowlist (no path
traversal); no auth (single-user system, localhost-only access already
enforced at the network layer).
"""
from __future__ import annotations

import re
from pathlib import Path

from flask import Blueprint, abort, send_from_directory


bp = Blueprint("aetheria_assets", __name__)

# ComfyUI's default output directory. Path.home() so the literal username
# never lands in tracked code (per the public-push scrub discipline).
COMFYUI_OUTPUT_DIR = Path.home() / "ComfyUI" / "output"

# Strict — only allow the filename pattern ComfyUI's SaveImage node produces:
# "<prefix>_<5-digit-counter>_.png" (or .webp etc.). Subfolders not allowed.
# We use a slightly relaxed pattern that covers all standard ComfyUI image
# extensions and counter widths.
_SAFE_FILENAME_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,127}\.(?:png|jpg|jpeg|webp|gif)$"
)


@bp.route("/aetheria/img/<filename>")
def serve_image(filename: str):
    """Serve a file from ~/ComfyUI/output/ if the name matches the safe
    pattern and the file exists. Returns 404 otherwise — no information
    leak about whether the path was malformed vs missing."""
    if not _SAFE_FILENAME_RE.match(filename):
        abort(404)
    if not COMFYUI_OUTPUT_DIR.is_dir():
        abort(404)
    # send_from_directory does its own directory-traversal protection
    # but the regex above is the primary defense.
    return send_from_directory(
        str(COMFYUI_OUTPUT_DIR),
        filename,
        as_attachment=False,
        max_age=3600,  # cacheable for an hour; images are immutable per filename
    )
