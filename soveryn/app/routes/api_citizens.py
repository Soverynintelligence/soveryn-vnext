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


@bp.get("/api/citizens/health")
def house_health():
    """One-glance house health (Rakazo-style named path, Soveryn evidence rules).

    Query:
      probe=0  — list worker units without systemctl (faster / CI-friendly)
    """
    state = current_app.extensions.get("soveryn") or {}
    loops = state.get("agent_loops") or {}
    probe = request.args.get("probe", "1").lower() not in ("0", "false", "no")
    from soveryn.citizens.house_health import assemble_house_health

    payload = assemble_house_health(
        db_path=_db_path(),
        agent_loops=list(loops.keys()),
        version=current_app.config.get("SOVERYN_VERSION", "0.0.0"),
        spawned=_spawned_under_aetheria(),
        probe_workers=probe,
    )
    # 200 even when ok=false — this is a status document, not a liveness probe.
    # Use GET /health for process-up; this is "is the polity coherent?"
    return jsonify(payload), 200


@bp.get("/api/active-now")
def active_now():
    """Who is mid-work right now — Active-now strip for Command Center.

    Composes running commissions (heartbeat / commission) with interactive
    chat busy (recent direct/messenger/signal/voice turns). Best-effort:
    missing DBs yield an empty list, never a 500.
    """
    state = current_app.extensions.get("soveryn") or {}
    env = state.get("env")
    conv_db = getattr(env, "conversations_db", None) if env is not None else None
    if conv_db is None:
        conv_store = state.get("conv_store")
        conv_db = getattr(conv_store, "db_path", None) if conv_store is not None else None
    from soveryn.citizens.active_now import build_active_now

    payload = build_active_now(_db_path(), conv_db)
    return jsonify(payload), 200


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


@bp.post("/api/citizens/runtime/drain")
def runtime_drain():
    """Drain one round of commissions (optional citizen_id). Localhost-only.

    Used by soveryn-scotty-worker (and ops) so a citizen unit can pull work
    without embedding AgentLoop in a second process.
    """
    _require_localhost()
    body = request.get_json(silent=True) or {}
    citizen_id = (body.get("citizen_id") or request.args.get("citizen_id") or "").strip()
    state = current_app.extensions.get("soveryn") or {}
    loops = state.get("agent_loops") or {}
    env = state.get("env")
    if not loops:
        return jsonify({
            "ok": False,
            "error": {"code": "no_loops", "message": "agent loops not ready"},
        }), 503
    path = _db_path()
    if not path.exists():
        return jsonify({
            "ok": False,
            "error": {"code": "no_registry", "message": "no citizens registry"},
        }), 503
    try:
        from soveryn.citizens.runtime import (
            drain_once,
            interactive_busy,
            make_agent_process_fn,
        )

        conv_store = state.get("conv_store")
        if conv_store is None:
            return jsonify({
                "ok": False,
                "error": {"code": "no_conv", "message": "conversation store missing"},
            }), 503

        process_fn = make_agent_process_fn(
            loops,
            conv_store,
            data_root=getattr(env, "data_root", None) if env is not None else None,
        )
        conv_db = getattr(env, "conversations_db", None) if env is not None else None

        def busy(cid: str) -> bool:
            return interactive_busy(conv_db, cid)

        ids = [citizen_id] if citizen_id else None
        closed = drain_once(
            path,
            process_fn=process_fn,
            worker=f"citizens-runtime/{citizen_id or 'all'}",
            citizen_ids=ids,
            busy_fn=busy,
            conv_store=conv_store,
            data_root=getattr(env, "data_root", None) if env is not None else None,
        )
        return jsonify({"ok": True, "closed": closed, "count": len(closed)}), 200
    except Exception as exc:
        return jsonify({
            "ok": False,
            "error": {"code": "drain_failed", "message": str(exc)},
        }), 500


@bp.get("/api/citizens/connectors")
def list_connectors():
    """Catalog + per-citizen grants/armed status for web, email, signal, …"""
    from soveryn.citizens.connectors import board_payload

    return jsonify(board_payload()), 200


@bp.get("/api/citizens/post")
def list_house_post():
    """Recent House Post traffic (all citizens)."""
    path = _db_path()
    if not path.exists():
        return jsonify({"posts": [], "chief_of_staff": "aetheria",
                        "note": "no registry yet"}), 200
    try:
        limit = min(int(request.args.get("limit", 40)), 100)
    except (TypeError, ValueError):
        limit = 40
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        return jsonify({"posts": [], "note": f"registry unreadable: {exc}"}), 200
    try:
        # Ensure schema exists even if only RO open failed migration — use empty
        from soveryn.citizens import post as house_post
        # RO connection cannot CREATE TABLE; if missing, return empty with note
        have = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='house_post'"
        ).fetchone()
        if have is None:
            return jsonify({
                "posts": [],
                "chief_of_staff": house_post.CHIEF_OF_STAFF_ID,
                "note": "house_post not migrated yet — run refresh census",
            }), 200
        posts = house_post.recent(conn, limit=limit)
        unread_cos = house_post.unread_for_cos(conn, limit=50)
        return jsonify({
            "posts": posts,
            "chief_of_staff": house_post.CHIEF_OF_STAFF_ID,
            "cos_unread": len(unread_cos),
            "reading": "house-local post; desks also get inbox/ copies",
        }), 200
    finally:
        conn.close()


@bp.post("/api/citizens/post")
def create_house_post():
    """Send a House Post memo/request/report. Localhost-only write.

    Body JSON:
      from_id, to_id, body, kind?, subject?
    Or route via COS:
      via_cos: true, assignee_id, body, subject?
      (from Jon: omit from_id — recorded as COS acting for Jon)
    """
    _require_localhost()
    body_json = request.get_json(silent=True) or {}
    body = body_json.get("body")
    if not isinstance(body, str) or not body.strip():
        return jsonify({
            "error": {"code": "missing_field",
                      "message": "Required field: body"},
        }), 400

    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from soveryn.citizens import post as house_post
        from soveryn.citizens.registry import connect as reg_connect

        with reg_connect(path) as conn:
            if body_json.get("via_cos"):
                assignee = (
                    body_json.get("assignee_id") or body_json.get("to_id") or ""
                ).strip()
                if not assignee:
                    return jsonify({
                        "error": {"code": "missing_field",
                                  "message": "via_cos requires assignee_id"},
                    }), 400
                raw_from = (body_json.get("from_id") or "jon").strip() or "jon"
                sender = (
                    raw_from
                    if raw_from in ("aetheria", "vett", "scotty")
                    else "aetheria"
                )
                note = body.strip()
                if raw_from not in ("aetheria", "vett", "scotty"):
                    note = f"(from Jon)\n\n{note}"
                result = house_post.route_via_cos(
                    conn,
                    from_id=sender,
                    assignee_id=assignee,
                    body=note,
                    at=_utc_now(),
                    subject=body_json.get("subject"),
                )
                return jsonify({"ok": True, "routed": result}), 201

            from_id = (body_json.get("from_id") or "").strip()
            to_id = (body_json.get("to_id") or "").strip()
            if not from_id or not to_id:
                return jsonify({
                    "error": {"code": "missing_field",
                              "message": "Required: from_id, to_id, body"},
                }), 400
            kind = (body_json.get("kind") or "memo").strip()
            post_id = house_post.send(
                conn,
                from_id=from_id,
                to_id=to_id,
                body=body.strip(),
                at=_utc_now(),
                kind=kind,
                subject=body_json.get("subject"),
            )
            row = conn.execute(
                "SELECT * FROM house_post WHERE id = ?", (post_id,)
            ).fetchone()
            return jsonify(dict(row) if row else {"id": post_id}), 201
    except ValueError as exc:
        return jsonify({"error": {"code": "invalid", "message": str(exc)}}), 400
    except sqlite3.IntegrityError as exc:
        return jsonify({"error": {"code": "invalid", "message": str(exc)}}), 400
    except Exception as exc:
        return jsonify({"error": {"code": "post_failed", "message": str(exc)}}), 500



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


def _approval_broker():
    """The Approval Gate broker wired at startup, or None if unavailable."""
    state = current_app.extensions.get("soveryn") or {}
    return state.get("approval_broker")


@bp.get("/api/approvals/pending")
def list_approvals_house():
    """Pending egress approvals house-wide (CC Needs-you / Gate strip).

    Best-effort read: a missing or locked gate yields an empty list with a
    note, never a 500.
    """
    broker = _approval_broker()
    if broker is None:
        return jsonify({
            "approvals": [],
            "count": 0,
            "note": "approval gate not wired",
        }), 200
    try:
        from dataclasses import asdict
        pending = broker.store.pending_all()
        return jsonify({
            "approvals": [asdict(r) for r in pending],
            "count": len(pending),
        }), 200
    except Exception as exc:
        return jsonify({
            "approvals": [],
            "count": 0,
            "note": f"approval store unreadable: {exc}",
        }), 200


@bp.get("/api/citizens/<citizen_id>/approvals")
def list_approvals(citizen_id: str):
    """Pending egress approvals held at the Approval Gate for one citizen.

    Best-effort read (charter evidence rules): a missing or locked gate yields
    an empty list with a note, never a 500. The decision surface lists what a
    human must answer before the blocked agent unblocks (or times out and the
    egress is denied fail-safe).
    """
    broker = _approval_broker()
    if broker is None:
        return jsonify({
            "approvals": [],
            "count": 0,
            "note": "approval gate not wired",
        }), 200
    try:
        from dataclasses import asdict
        pending = broker.store.pending_for(citizen_id)
        return jsonify({
            "approvals": [asdict(r) for r in pending],
            "count": len(pending),
        }), 200
    except Exception as exc:
        return jsonify({
            "approvals": [],
            "count": 0,
            "note": f"approval store unreadable: {exc}",
        }), 200


@bp.post("/api/citizens/<citizen_id>/approvals/<approval_id>/decision")
def decide_approval(citizen_id: str, approval_id: str):
    """Approve or deny a pending egress call held at the Approval Gate.

    Localhost-only write (the gate is a human authority, not an API client).
    Body JSON: {"approve": true|false, "decided_by": "jon"} (decided_by
    defaults to "jon"). Once decided, a request stays decided — a second
    decision is a no-op, not an error.

    Fail-safe contract: anything that is not an explicit approve leaves the
    egress denied (the broker also expires unanswered requests on timeout).
    """
    _require_localhost()
    broker = _approval_broker()
    if broker is None:
        return jsonify({
            "error": {
                "code": "gate_unavailable",
                "message": "approval gate not wired at startup",
            }
        }), 503

    body_json = request.get_json(silent=True) or {}
    approve = body_json.get("approve")
    if not isinstance(approve, bool):
        return jsonify({
            "error": {
                "code": "missing_field",
                "message": "Required field: approve (true|false)",
            }
        }), 400
    decided_by = (body_json.get("decided_by") or "jon").strip() or "jon"

    updated = broker.decide(
        approval_id,
        approve=approve,
        decided_by=decided_by,
        now=_utc_now(),
    )
    if updated is None:
        return jsonify({
            "error": {
                "code": "not_found",
                "message": f"no approval request {approval_id!r}",
            }
        }), 404
    if updated.citizen and updated.citizen != citizen_id:
        return jsonify({
            "error": {
                "code": "wrong_citizen",
                "message": (
                    f"approval {approval_id!r} belongs to "
                    f"{updated.citizen!r}, not {citizen_id!r}"
                ),
            }
        }), 409
    from dataclasses import asdict
    return jsonify(asdict(updated)), 200
