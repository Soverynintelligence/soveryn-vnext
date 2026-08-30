"""SOVERYN vNext — /api/system/* read-only system stats."""

from __future__ import annotations
import sqlite3
from dataclasses import asdict
from datetime import datetime

from flask import Blueprint, current_app, jsonify, request

from soveryn.app.services.bench_flash import chat as bench_flash_chat
from soveryn.app.services.bench_flash import get_status as bench_flash_status
from soveryn.app.services.bench_flash import start_warm as bench_flash_warm
from soveryn.app.services.gpu_stats import get_gpu_stats
from soveryn.app.services.public_agents import get_public_agents
from soveryn.app.services.rig_stats import get_rig_stats
from soveryn.app.services.spark_stats import get_spark_stats, get_spark2_stats

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


@bp.get("/api/system/rig")
def api_system_rig():
    """The Rig panel: which model/agent occupies which GPU, and how much VRAM
    each resident takes — the fact `/api/system/gpu` can't answer.
    """
    r = get_rig_stats()
    return jsonify({
        "available": r.available,
        "message": r.message,
        "gpus": [asdict(g) for g in r.gpus],
        "fetched_at": r.fetched_at,
        "residents_known": r.residents_known,
    }), 200


@bp.get("/api/system/spark")
def api_system_spark():
    """DGX Spark: box health + vLLM serving state.

    `path` is "fabric" | "wifi" | null. WiFi means the 200G link is DOWN and we
    silently fell back to a ~100x slower path — the UI renders that amber, not green.
    """
    r = get_spark_stats()
    b = get_spark2_stats()
    return jsonify({
        "available": r.available,
        "path": r.path,
        "message": r.message,
        "host": asdict(r.host) if r.host else None,
        "containers": [asdict(c) for c in r.containers],
        "vllm": asdict(r.vllm) if r.vllm else None,
        "fetched_at": r.fetched_at,
        "host_known": r.host_known,
        "b": {
            "available": b.available,
            "path": b.path,
            "message": b.message,
            "host": asdict(b.host) if b.host else None,
            "containers": [asdict(c) for c in b.containers],
            "vllm": asdict(b.vllm) if b.vllm else None,
            "fetched_at": b.fetched_at,
            "host_known": b.host_known,
        },
    }), 200


@bp.get("/api/system/public_agents")
def api_system_public_agents():
    """PondWright / Seneca / Atticus glance for Mission Control.

    Probes Spark fabric ports directly (not public hostnames) so a Cloudflare
    tunnel blip does not blank the panels. Summary payloads are counts + short
    previews only — never full transcripts, never lattice writes.
    """
    return jsonify(get_public_agents()), 200


@bp.get("/api/system/acttruth")
def api_system_acttruth():
    """ActTruth by SOVERYN — crew act ledger + unprompted spend budgets.

    Thin glance for Mission Control. Not Lattice; not black_box forensics.
    """
    from soveryn.platform.acttruth.unprompted import crew_status

    try:
        snap = crew_status(limit=4)
        return jsonify({
            "available": True,
            "brand": "ActTruth by SOVERYN",
            "site": "https://acttruth.com",
            **snap,
            "fetched_at": datetime.now().isoformat(),
        }), 200
    except Exception as exc:  # noqa: BLE001 — glance must never 500 the CC
        return jsonify({
            "available": False,
            "message": f"{type(exc).__name__}: {exc}",
            "fetched_at": datetime.now().isoformat(),
        }), 200


@bp.get("/api/system/acttruth/triage")
def api_system_acttruth_triage():
    """ActTruth Step 3 — open bug-triage candidates (lesson streaks → durable-fix queue).

    Does not auto-fix. See docs/designs/2026-08-20-acttruth-bug-triage.md.
    """
    from soveryn.platform.acttruth.triage import list_triage

    try:
        limit = int(request.args.get("limit") or 40)
    except ValueError:
        limit = 40
    status = request.args.get("status")
    if status is None:
        status = "open"
    if status in ("", "all", "*"):
        status = None
    try:
        items = list_triage(limit=limit, status=status)
        return jsonify({
            "ok": True,
            "available": True,
            "brand": "ActTruth by SOVERYN",
            "count": len(items),
            "status_filter": status or "all",
            "triage": items,
            "note": "Step 3 candidates — classify then skill/code/ops; no auto-fix",
            "fetched_at": datetime.now().isoformat(),
        }), 200
    except Exception as exc:  # noqa: BLE001 — glance must never 500 the CC
        return jsonify({
            "ok": False,
            "available": False,
            "message": f"{type(exc).__name__}: {exc}",
            "triage": [],
            "fetched_at": datetime.now().isoformat(),
        }), 200


@bp.get("/api/system/acttruth/proof")
def api_system_acttruth_proof():
    """Honest ActTruth stats + shareable proof blurb (ledger receipts only)."""
    from soveryn.platform.acttruth.proof import collect_proof, format_proof_post

    try:
        hours = request.args.get("hours", "24")
        try:
            window = float(hours)
        except ValueError:
            window = 24.0
        window = max(1.0, min(window, 24 * 30))
        run_tests = request.args.get("pytest", "0") in ("1", "true", "yes")
        style = request.args.get("style", "x")
        if style not in ("x", "markdown"):
            style = "x"
        proof = collect_proof(window_hours=window, include_pytest=run_tests)
        return jsonify({
            "available": True,
            "brand": "ActTruth by SOVERYN",
            "proof": proof.to_dict(),
            "post": format_proof_post(proof, style=style),
            "fail_rate_pct": proof.fail_rate(),
        }), 200
    except Exception as exc:  # noqa: BLE001
        return jsonify({
            "available": False,
            "message": f"{type(exc).__name__}: {exc}",
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


@bp.get("/api/system/bench_flash")
def api_system_bench_flash():
    """Kernel (build brain) — weights, router, warm/cold state."""
    return jsonify(bench_flash_status().as_dict()), 200


@bp.post("/api/system/bench_flash/warm")
def api_system_bench_flash_warm():
    """Start loading Kernel (glm-5.3-flash on Spark :8001) in the background."""
    result = bench_flash_warm()
    code = 200 if result.get("ok") else 409
    return jsonify(result), code


@bp.post("/api/system/bench_flash/chat")
def api_system_bench_flash_chat():
    """Kernel chat with optional HITL tools (default on)."""
    body = request.get_json(silent=True) or {}
    message = str(body.get("message") or body.get("content") or "")
    history = body.get("history") if isinstance(body.get("history"), list) else None
    max_tokens = body.get("max_tokens")
    temperature = body.get("temperature")
    tools = body.get("tools")
    if tools is None:
        tools = True
    kwargs: dict = {"tools": bool(tools)}
    if isinstance(max_tokens, int) and 1 <= max_tokens <= 8192:
        kwargs["max_tokens"] = max_tokens
    if isinstance(temperature, (int, float)) and 0 <= float(temperature) <= 2:
        kwargs["temperature"] = float(temperature)
    mtr = body.get("max_tool_rounds")
    if isinstance(mtr, int) and 1 <= mtr <= 8:
        kwargs["max_tool_rounds"] = mtr
    result = bench_flash_chat(message, history=history, **kwargs)
    code = 200 if result.get("ok") else 400
    return jsonify(result), code


@bp.get("/api/system/bench_flash/proposals")
def api_system_bench_flash_proposals():
    """List Kernel HITL proposals (default: pending)."""
    from soveryn.app.services.kernel_hitl import list_proposals, workspaces

    status = request.args.get("status", "pending")
    if status in ("", "all", "*"):
        status = None
    return jsonify(
        {
            "proposals": list_proposals(status=status, limit=50),
            "workspaces": [str(w) for w in workspaces()],
        }
    ), 200


@bp.post("/api/system/bench_flash/proposals/<proposal_id>/approve")
def api_system_bench_flash_proposal_approve(proposal_id: str):
    """Operator approved a Kernel write/shell proposal — execute it."""
    from soveryn.app.services.kernel_hitl import execute_proposal, load_proposal

    prop = load_proposal(proposal_id)
    if prop is None:
        return jsonify({"ok": False, "error": "not_found"}), 404
    if prop.status not in ("pending", "approved"):
        return jsonify({"ok": False, "error": f"status={prop.status}", "proposal": prop.as_dict()}), 409
    done = execute_proposal(prop)
    code = 200 if done.status == "executed" else 400
    return jsonify({"ok": done.status == "executed", "proposal": done.as_dict()}), code


@bp.post("/api/system/bench_flash/proposals/<proposal_id>/reject")
def api_system_bench_flash_proposal_reject(proposal_id: str):
    """Operator rejected a Kernel proposal."""
    from soveryn.app.services.kernel_hitl import load_proposal, reject_proposal

    prop = load_proposal(proposal_id)
    if prop is None:
        return jsonify({"ok": False, "error": "not_found"}), 404
    body = request.get_json(silent=True) or {}
    reason = str(body.get("reason") or "")
    done = reject_proposal(prop, reason=reason)
    return jsonify({"ok": True, "proposal": done.as_dict()}), 200


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
