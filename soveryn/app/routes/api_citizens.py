"""SOVERYN vNext — /api/citizens — who is resident, and the commissions queue.

Charter §9.4: the status surface for the polity. Read roster is best-effort —
a missing or locked registry yields an empty roster, never a 500.

Commissions (Phase 2 / charter §12.4) are the write path: Jon (or a duty)
enqueues work; the citizens runtime drains it; results land in outbox/.

What GET /api/citizens will NOT do
---------------------------------
It does not probe anything. It reports the registry's derived status from
recorded observations (and `on_duty` when a commission is running). Taking
the census is a separate act: `python -m soveryn.citizens.census`.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, abort, current_app, jsonify, request

bp = Blueprint("api_citizens", __name__)

_DEFAULT_DB = Path.home() / "soveryn_vnext" / "data" / "citizens.db"
_LOCALHOST_ADDRS = {"127.0.0.1", "::1"}


def _db_path() -> Path:
    configured = (current_app.config.get("CITIZENS_DB")
                  or os.environ.get("SOVERYN_CITIZENS_DB"))
    return Path(configured) if configured else _DEFAULT_DB


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_localhost():
    if request.remote_addr not in _LOCALHOST_ADDRS:
        abort(403, description="citizens write endpoints require localhost")


def _open_rw():
    path = _db_path()
    if not path.exists():
        return None, jsonify({
            "error": {
                "code": "no_registry",
                "message": "no registry yet — run the census",
            }
        }), 503
    try:
        conn = sqlite3.connect(str(path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn, None, None
    except sqlite3.Error as exc:
        return None, jsonify({
            "error": {
                "code": "registry_unreadable",
                "message": str(exc),
            }
        }), 503


def _spawned_under_aetheria() -> dict:
    """Ephemeral specialists Aetheria has spawned — NOT citizens.

    Charter: specialists have no soul, desk, or standing. They are session-
    scoped deputies (usually on vett/scotty) created by Aetheria's
    spawn_specialist tool. The Citizens board surfaces them as *visitors
    under Aetheria* so the house can see them without diluting the polity.
    """
    from dataclasses import asdict

    empty = {
        "host_citizen": "aetheria",
        "kind": "specialist",
        "note": (
            "Ephemeral deputies Aetheria spawns for one job — not founding "
            "citizens. No soul, no desk, no standing. Empty most days is fine."
        ),
        "specialists": [],
        "count": 0,
    }
    try:
        state = current_app.extensions.get("soveryn") or {}
        env = state.get("env")
        if env is None or not getattr(env, "conversations_db", None):
            return empty
        from soveryn.app.services.specialists_view import list_active_specialists
        active = list_active_specialists(env.conversations_db)
        rows = []
        for s in active:
            d = asdict(s)
            # Always attribute the spawn to Aetheria's authority, even though
            # the session runs on vett/scotty as the host agent runtime.
            d["spawned_by"] = "aetheria"
            d["standing"] = "ephemeral"  # never resident / never a citizen
            rows.append(d)
        empty["specialists"] = rows
        empty["count"] = len(rows)
        return empty
    except Exception:
        # Board must not 500 if the conv DB is mid-migrate or locked.
        empty["note"] = empty["note"] + " (spawned list unavailable right now)"
        return empty


@bp.route("/api/citizens", methods=["GET"])
def citizens():
    path = _db_path()
    if not path.exists():
        return jsonify({
            "citizens": [],
            "spawned": _spawned_under_aetheria(),
            "note": "no registry yet — run the census",
        }), 200

    try:
        # read-only: a status surface must never be able to write the registry
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        return jsonify({
            "citizens": [],
            "spawned": _spawned_under_aetheria(),
            "note": f"registry unreadable: {exc}",
        }), 200

    try:
        from soveryn.citizens.registry import board_citizens
        rows = board_citizens(conn)
    except sqlite3.Error as exc:
        return jsonify({
            "citizens": [],
            "spawned": _spawned_under_aetheria(),
            "note": f"registry unreadable: {exc}",
        }), 200
    finally:
        conn.close()

    spawned = _spawned_under_aetheria()
    # Surface a count on Aetheria's row without inventing citizenship.
    for row in rows:
        if row.get("id") == "aetheria":
            row["spawned_count"] = spawned["count"]
            break

    return jsonify({
        "citizens": rows,
        "spawned": spawned,
        "counts": {
            state: sum(1 for r in rows if r["status"] == state)
            for state in ("resident", "on_duty", "blocked",
                          "offline", "unobserved", "retired")
        },
        # Said in the payload so no consumer has to guess, and so a client that
        # lights a dot from this cannot claim the reading is fresher than it is.
        "reading": "derived from last census + commission state; not probed on request",
    }), 200


@bp.post("/api/citizens/refresh")
def refresh_census():
    """Re-probe process residences and re-seed founding duties. Localhost-only."""
    _require_localhost()
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from soveryn.citizens.census import take_census
        from soveryn.citizens.registry import connect
        with connect(path) as conn:
            rows = take_census(conn)
    except Exception as exc:
        return jsonify({
            "error": {"code": "census_failed", "message": str(exc)}
        }), 500
    spawned = _spawned_under_aetheria()
    for row in rows:
        if row.get("id") == "aetheria":
            row["spawned_count"] = spawned["count"]
            break
    return jsonify({
        "citizens": rows,
        "spawned": spawned,
        "counts": {
            state: sum(1 for r in rows if r["status"] == state)
            for state in ("resident", "on_duty", "blocked",
                          "offline", "unobserved", "retired")
        },
        "reading": "fresh census just now",
    }), 200


@bp.get("/api/citizens/<citizen_id>")
def citizen_one(citizen_id: str):
    path = _db_path()
    if not path.exists():
        return jsonify({"error": {"code": "no_registry",
                                  "message": "no registry yet"}}), 404
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        return jsonify({"error": {"code": "registry_unreadable",
                                  "message": str(exc)}}), 503
    try:
        from soveryn.citizens.registry import board_citizens
        from soveryn.citizens.commissions import is_running
        rows = [r for r in board_citizens(conn) if r["id"] == citizen_id]
        if not rows:
            return jsonify({"error": {"code": "not_found",
                                      "message": f"no citizen {citizen_id!r}"}}), 404
        row = rows[0]
        row["on_duty_now"] = is_running(conn, citizen_id)
        return jsonify(row), 200
    finally:
        conn.close()


@bp.get("/api/citizens/<citizen_id>/duties")
def list_duties(citizen_id: str):
    path = _db_path()
    if not path.exists():
        return jsonify({"duties": [], "note": "no registry yet"}), 200
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        return jsonify({"duties": [], "note": f"registry unreadable: {exc}"}), 200
    try:
        exists = conn.execute(
            "SELECT 1 FROM citizens WHERE id = ?", (citizen_id,)
        ).fetchone()
        if exists is None:
            return jsonify({"error": {"code": "not_found",
                                      "message": f"no citizen {citizen_id!r}"}}), 404
        from soveryn.citizens.duties import for_citizen as duties_for
        return jsonify({
            "citizen_id": citizen_id,
            "duties": duties_for(conn, citizen_id),
        }), 200
    finally:
        conn.close()


@bp.get("/api/citizens/<citizen_id>/commissions")
def list_commissions(citizen_id: str):
    path = _db_path()
    if not path.exists():
        return jsonify({"commissions": [], "note": "no registry yet"}), 200
    state = request.args.get("state")
    try:
        limit = min(int(request.args.get("limit", 50)), 200)
    except (TypeError, ValueError):
        limit = 50
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        return jsonify({"commissions": [], "note": f"registry unreadable: {exc}"}), 200
    try:
        from soveryn.citizens.commissions import for_citizen
        # Verify citizen exists by attempting list with FK-ish check via registry
        exists = conn.execute(
            "SELECT 1 FROM citizens WHERE id = ?", (citizen_id,)
        ).fetchone()
        if exists is None:
            return jsonify({"error": {"code": "not_found",
                                      "message": f"no citizen {citizen_id!r}"}}), 404
        rows = for_citizen(conn, citizen_id, limit=limit, state=state)
        return jsonify({"citizen_id": citizen_id, "commissions": rows}), 200
    finally:
        conn.close()


@bp.post("/api/citizens/<citizen_id>/commissions")
def create_commission(citizen_id: str):
    """Enqueue work for a citizen. Localhost-only write."""
    _require_localhost()
    body_json = request.get_json(silent=True) or {}
    body = body_json.get("body")
    title = body_json.get("title")
    if not isinstance(body, str) or not body.strip():
        return jsonify({
            "error": {
                "code": "missing_field",
                "message": "Required field: body (what is being asked)",
            }
        }), 400
    text = body.strip()
    if isinstance(title, str) and title.strip():
        text = f"{title.strip()}\n\n{text}"

    conn, err, code = _open_rw()
    if err is not None:
        return err, code
    assert conn is not None
    try:
        from soveryn.citizens import commissions
        exists = conn.execute(
            "SELECT 1 FROM citizens WHERE id = ?", (citizen_id,)
        ).fetchone()
        if exists is None:
            return jsonify({
                "error": {
                    "code": "not_found",
                    "message": f"no citizen {citizen_id!r}",
                }
            }), 404
        retired = conn.execute(
            "SELECT retired_at FROM citizens WHERE id = ?", (citizen_id,)
        ).fetchone()
        if retired and retired["retired_at"]:
            return jsonify({
                "error": {
                    "code": "retired",
                    "message": f"citizen {citizen_id!r} is retired",
                }
            }), 409
        cid = commissions.enqueue(
            conn, citizen_id, text, at=_utc_now()
        )
        row = commissions.get(conn, cid)
        return jsonify(row), 201
    except ValueError as exc:
        return jsonify({"error": {"code": "invalid", "message": str(exc)}}), 400
    except sqlite3.IntegrityError as exc:
        return jsonify({"error": {"code": "invalid", "message": str(exc)}}), 400
    finally:
        conn.close()


@bp.get("/api/commissions/<commission_id>")
def get_commission(commission_id: str):
    path = _db_path()
    if not path.exists():
        return jsonify({"error": {"code": "no_registry",
                                  "message": "no registry yet"}}), 404
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        return jsonify({"error": {"code": "registry_unreadable",
                                  "message": str(exc)}}), 503
    try:
        from soveryn.citizens.commissions import get
        row = get(conn, commission_id)
        if row is None:
            return jsonify({"error": {"code": "not_found",
                                      "message": f"no commission {commission_id!r}"}}), 404
        return jsonify(row), 200
    finally:
        conn.close()


@bp.post("/api/commissions/<commission_id>/cancel")
def cancel_commission(commission_id: str):
    _require_localhost()
    body_json = request.get_json(silent=True) or {}
    reason = body_json.get("reason") or "cancelled by operator"
    if not isinstance(reason, str):
        reason = "cancelled by operator"

    conn, err, code = _open_rw()
    if err is not None:
        return err, code
    assert conn is not None
    try:
        from soveryn.citizens import commissions
        try:
            row = commissions.cancel(
                conn, commission_id, at=_utc_now(), reason=reason
            )
        except KeyError:
            return jsonify({
                "error": {
                    "code": "not_found",
                    "message": f"no commission {commission_id!r}",
                }
            }), 404
        except ValueError as exc:
            return jsonify({
                "error": {"code": "not_cancellable", "message": str(exc)}
            }), 409
        return jsonify(row), 200
    finally:
        conn.close()
