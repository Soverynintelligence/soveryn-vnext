"""SOVERYN vNext — /api/heartbeat/* — heartbeat pulse surface for Mission Control.

Closes the read-only loop the 2026-06-15 Coordination Blackout arc surfaced:
Aetheria's heartbeat ticks were happening invisibly (audit log only). This
endpoint feeds the Mission Control heartbeat panel so the rhythm becomes
Jon's surface, separate from any chat content she chooses to surface via
the new [SURFACE]/[NO_OP] decision pattern.

Endpoints:
- GET /api/heartbeat/recent?limit=N  — most recent N pulses (default 20, max 100).

Reads from `heartbeat_log` in lattice_vnext.db. No-auth (the surrounding
localhost guard in startup.py + the funnel config gate are the access layer).
"""

from __future__ import annotations
import json
import os
import sqlite3

from flask import Blueprint, current_app, jsonify, request


bp = Blueprint("api_heartbeat", __name__)


DEFAULT_LIMIT = 20
MAX_LIMIT = 100


# ── pulse notes ─────────────────────────────────────────────────────────────
# heartbeat_log records that a pulse HAPPENED; the note she actually wrote lives
# in the ThoughtsLog jsonl, keyed by pulse_id. Without joining them the panel can
# only say "silent", which is how ~727k characters of her reflection went unread
# between 2026-07-12 and 07-27: surfacing to a primary chat was removed (721fb93,
# correctly — it minted a new chat every 30 min) and nothing replaced it.
_THOUGHTS = os.path.expanduser("~/soveryn_vnext/data/heartbeat_thoughts.jsonl")
_TAIL_BYTES = 512 * 1024      # plenty for the last few hundred pulses


def _notes_by_pulse(path: str = _THOUGHTS) -> dict:
    """Map pulse_id -> note, reading only the tail so this stays cheap."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > _TAIL_BYTES:
                fh.seek(size - _TAIL_BYTES)
                fh.readline()                 # discard the partial first line
            raw = fh.read().decode("utf-8", "replace")
    except OSError:
        return {}

    out: dict = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        pid, note = rec.get("pulse_id"), (rec.get("note") or "").strip()
        if pid and note:
            out[pid] = note
    return out


def _state():
    return current_app.extensions["soveryn"]


@bp.get("/api/heartbeat/recent")
def api_heartbeat_recent():
    """Return the most recent N heartbeat pulses.

    Shape:
    {
        "pulses": [
            {
                "id": "...",
                "triggered_at": "...",
                "completed_at": "...",
                "eligible": bool,
                "skip_reason": str | None,
                "surfaced_to_chat": bool,
                "action_taken": bool | None,
                "tool_call_count": int | None,
                "response_length": int | None,
                "error": str | None,
                "dry_run": bool,
            },
            ...
        ]
    }

    Empty `pulses` is a valid empty-state — fresh DB, daemon not started yet,
    or heartbeat_log table missing. Never 5xx for read-only emptiness.
    """
    raw_limit = request.args.get("limit", default=str(DEFAULT_LIMIT))
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    if limit < 1:
        limit = 1
    if limit > MAX_LIMIT:
        limit = MAX_LIMIT

    env = _state()["env"]
    lattice_db = str(env.lattice_db)
    pulses: list[dict] = []
    try:
        with sqlite3.connect(lattice_db) as con:
            con.row_factory = sqlite3.Row
            # surfaced_to_chat may not exist on legacy DBs that haven't
            # picked up the 2026-06-15 migration yet — both the daemon AND
            # LatticeStore._init_schema attempt the ALTER on startup, but be
            # defensive at the read site too. PRAGMA-check once per request
            # so a fresh / older DB doesn't 500 the panel.
            cols = {
                r["name"]
                for r in con.execute("PRAGMA table_info(heartbeat_log)").fetchall()
            }
            has_surfaced = "surfaced_to_chat" in cols
            select_surfaced = (
                "surfaced_to_chat" if has_surfaced else "0 AS surfaced_to_chat"
            )
            rows = con.execute(
                f"SELECT id, triggered_at, completed_at, eligible, skip_reason, "
                f"action_taken, tool_call_count, response_length, error, "
                f"dry_run, {select_surfaced} "
                f"FROM heartbeat_log ORDER BY triggered_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    except sqlite3.OperationalError:
        # Table missing or DB not yet initialized — return empty pulses.
        return jsonify({"pulses": []}), 200

    notes = _notes_by_pulse()

    for r in rows:
        pulses.append({
            "note": notes.get(r["id"]),          # what she actually wrote, if anything
            "id": r["id"],
            "triggered_at": r["triggered_at"],
            "completed_at": r["completed_at"],
            "eligible": bool(r["eligible"]),
            "skip_reason": r["skip_reason"],
            "surfaced_to_chat": bool(r["surfaced_to_chat"]),
            "action_taken": (
                None if r["action_taken"] is None else bool(r["action_taken"])
            ),
            "tool_call_count": r["tool_call_count"],
            "response_length": r["response_length"],
            "error": r["error"],
            "dry_run": bool(r["dry_run"]),
        })

    return jsonify({"pulses": pulses}), 200
