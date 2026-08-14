"""SOVERYN vNext — /api/citizens — who is resident, and on what evidence.

Charter §9.4: the status surface for the polity. Read-only, best-effort — a
missing or locked registry yields an empty roster, never a 500, in the same
spirit as the Ares surface.

What this endpoint will NOT do
------------------------------
It does not probe anything. It reports the registry's derived status, and the
registry derives status only from recorded observations (see
`soveryn.citizens.registry`). Taking the census is a separate, deliberate act —
`python -m soveryn.citizens.census` — so that a page load can never be mistaken
for evidence that a Citizen is alive.

Consequently `status` here can be `unobserved`, and callers must render that
distinctly from `offline`. They are different claims: `offline` means someone
looked and found nothing; `unobserved` means nobody has looked, which is the
honest state for a Citizen with no resident process (Scotty) or one whose
process this host cannot see.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from flask import Blueprint, current_app, jsonify

bp = Blueprint("api_citizens", __name__)

_DEFAULT_DB = Path.home() / "soveryn_vnext" / "data" / "citizens.db"


def _db_path() -> Path:
    configured = (current_app.config.get("CITIZENS_DB")
                  or os.environ.get("SOVERYN_CITIZENS_DB"))
    return Path(configured) if configured else _DEFAULT_DB


@bp.route("/api/citizens", methods=["GET"])
def citizens():
    path = _db_path()
    if not path.exists():
        return jsonify({"citizens": [], "note": "no registry yet — run the census"}), 200

    try:
        # read-only: a status surface must never be able to write the registry
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        return jsonify({"citizens": [], "note": f"registry unreadable: {exc}"}), 200

    try:
        from soveryn.citizens.registry import list_citizens
        rows = list_citizens(conn)
    except sqlite3.Error as exc:
        return jsonify({"citizens": [], "note": f"registry unreadable: {exc}"}), 200
    finally:
        conn.close()

    return jsonify({
        "citizens": rows,
        "counts": {
            state: sum(1 for r in rows if r["status"] == state)
            for state in ("resident", "on_duty", "blocked",
                          "offline", "unobserved", "retired")
        },
        # Said in the payload so no consumer has to guess, and so a client that
        # lights a dot from this cannot claim the reading is fresher than it is.
        "reading": "derived from the last recorded census, not probed on request",
    }), 200
