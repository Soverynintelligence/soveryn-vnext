"""SOVERYN vNext — /api/system/* read-only system stats."""

from __future__ import annotations
import sqlite3
from dataclasses import asdict
from datetime import datetime

from flask import Blueprint, current_app, jsonify

from soveryn.app.services.gpu_stats import get_gpu_stats
from soveryn.app.services.spark_stats import get_spark_stats

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


@bp.get("/api/system/spark")
def api_system_spark():
    """DGX Spark: box health + vLLM serving state.

    `path` is "fabric" | "wifi" | null. WiFi means the 200G link is DOWN and we
    silently fell back to a ~100x slower path — the UI renders that amber, not green.
    """
    r = get_spark_stats()
    return jsonify({
        "available": r.available,
        "path": r.path,
        "message": r.message,
        "host": asdict(r.host) if r.host else None,
        "containers": [asdict(c) for c in r.containers],
        "vllm": asdict(r.vllm) if r.vllm else None,
        "fetched_at": r.fetched_at,
    }), 200


@bp.get("/api/system/daemons")
def api_system_daemons():
    """Last-tick state of each autonomous daemon (heartbeat, vett patrol, ares).

    Cheap DB read of the most recent row per log table. Returns a stable
    shape with `status` in {"active","stale","unknown"} so the UI can color-code
    without knowing the underlying schema. "stale" fires when the last tick
    is older than the daemon's expected interval; "unknown" when no rows
    exist at all.
    """
    env = current_app.extensions["soveryn"]["env"]
    lattice_db = str(env.lattice_db)
    return jsonify({
        "heartbeat": _heartbeat_summary(lattice_db),
        "patrol":    _patrol_summary(lattice_db),
        "ares":      _ares_summary(lattice_db),
        "fetched_at": datetime.now().isoformat(),
    }), 200


# Per-daemon "stale" thresholds (seconds). If the last tick is older than this,
# UI shows the daemon as stale instead of active. Heartbeat = 2x interval,
# patrol = 1.5x interval so a single missed tick doesn't trigger stale.
HEARTBEAT_STALE_SECONDS = 3600          # heartbeat at 30min => stale at 1h
PATROL_STALE_SECONDS = 32400            # patrol at 6h => stale at 9h
ARES_STALE_SECONDS = 3600               # ares posts on its own cadence; 1h ok


def _heartbeat_summary(lattice_db: str) -> dict:
    try:
        with sqlite3.connect(lattice_db) as con:
            con.row_factory = sqlite3.Row
            row = con.execute(
                "SELECT triggered_at, eligible, skip_reason, action_taken, "
                "tool_call_count, response_length, error, dry_run "
                "FROM heartbeat_log ORDER BY triggered_at DESC LIMIT 1"
            ).fetchone()
    except sqlite3.OperationalError:
        return _unknown_daemon("heartbeat")
    if row is None:
        return _unknown_daemon("heartbeat")
    return _wrap_daemon_row(
        name="heartbeat",
        triggered_at=row["triggered_at"],
        stale_seconds=HEARTBEAT_STALE_SECONDS,
        extras={
            "eligible": bool(row["eligible"]),
            "skip_reason": row["skip_reason"],
            "action_taken": (
                None if row["action_taken"] is None else bool(row["action_taken"])
            ),
            "tool_call_count": row["tool_call_count"],
            "response_length": row["response_length"],
            "error": row["error"],
            "dry_run": bool(row["dry_run"]),
        },
    )


def _patrol_summary(lattice_db: str) -> dict:
    try:
        with sqlite3.connect(lattice_db) as con:
            con.row_factory = sqlite3.Row
            row = con.execute(
                "SELECT triggered_at, eligible, skip_reason, sources_visited, "
                "signals_posted, response_length, error, dry_run "
                "FROM vett_patrol_log ORDER BY triggered_at DESC LIMIT 1"
            ).fetchone()
    except sqlite3.OperationalError:
        return _unknown_daemon("patrol")
    if row is None:
        return _unknown_daemon("patrol")
    return _wrap_daemon_row(
        name="patrol",
        triggered_at=row["triggered_at"],
        stale_seconds=PATROL_STALE_SECONDS,
        extras={
            "eligible": bool(row["eligible"]),
            "skip_reason": row["skip_reason"],
            "sources_visited": row["sources_visited"],
            "signals_posted": row["signals_posted"],
            "response_length": row["response_length"],
            "error": row["error"],
            "dry_run": bool(row["dry_run"]),
        },
    )


def _ares_summary(lattice_db: str) -> dict:
    """Ares writes Signals when something needs attention; we proxy his pulse
    via "most recent ares-authored coord node" since he doesn't have a
    dedicated log table. If he hasn't surfaced in a while, he's still alive
    — silence is his normal state. Mark stale only on long gaps."""
    try:
        with sqlite3.connect(lattice_db) as con:
            con.row_factory = sqlite3.Row
            row = con.execute(
                "SELECT created_at FROM nodes "
                "WHERE agent = 'ares' AND type = 'coordination' "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
    except sqlite3.OperationalError:
        return _unknown_daemon("ares")
    if row is None:
        # Ares hasn't posted ever — that's actually OK, means nothing's
        # broken. Use a different "quiet" status so UI doesn't alarm.
        return {"name": "ares", "status": "quiet", "last_tick": None}
    return _wrap_daemon_row(
        name="ares",
        triggered_at=row["created_at"],
        stale_seconds=ARES_STALE_SECONDS,
        extras={"signal_posted": True},
    )


def _wrap_daemon_row(*, name: str, triggered_at: str, stale_seconds: int,
                      extras: dict) -> dict:
    age_seconds = _age_seconds(triggered_at)
    if age_seconds is None:
        status = "unknown"
    elif age_seconds > stale_seconds:
        status = "stale"
    else:
        status = "active"
    return {
        "name": name,
        "status": status,
        "last_tick": triggered_at,
        "age_seconds": age_seconds,
        **extras,
    }


def _unknown_daemon(name: str) -> dict:
    return {"name": name, "status": "unknown", "last_tick": None}


def _age_seconds(iso_ts: str | None) -> int | None:
    if not iso_ts:
        return None
    try:
        ts = datetime.fromisoformat(iso_ts)
    except ValueError:
        return None
    return int((datetime.now() - ts).total_seconds())
