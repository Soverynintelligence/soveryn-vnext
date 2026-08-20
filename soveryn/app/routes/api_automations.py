"""Command Center API for Automations (scheduler + CC inbox; Signal preview-only)."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from flask import Blueprint, current_app, jsonify, request

from soveryn.automations.inbox import append_inbox, list_inbox
from soveryn.automations.prefs import (
    AVAILABLE_CHANNELS,
    resolve_channels,
    set_channels,
)
from soveryn.automations.registry import get_automation, load_automations
from soveryn.automations.routines import load_routine, routine_summary
from soveryn.automations.runner import run_automation
from soveryn.automations.schedule import record_fire

bp = Blueprint("api_automations", __name__)

# Hard gate this pass — Hermes-style: local delivery first, egress later.
_SIGNAL_LIVE = False


def _in_process_context():
    """Return (agent_loops, conv_store) from the running app, or (None, None)."""
    ext = current_app.extensions.get("soveryn") or {}
    return ext.get("agent_loops"), ext.get("conv_store")


def _spec_to_dict(spec) -> dict:
    d = asdict(spec)
    channels = resolve_channels(spec.id)
    d["channels"] = channels
    d["available_channels"] = list(AVAILABLE_CHANNELS)
    d["delivery_effective"] = {
        "channels": channels,
        "channel": channels[0] if channels else "command_center",
        "target": spec.delivery.target,
    }
    d["signal_live_armed"] = _SIGNAL_LIVE
    d.update(routine_summary(spec.id))
    return d


def _maybe_inbox(result: dict, *, source: str) -> dict | None:
    """Write CC inbox for every live run. Signal never sent this pass.

    Hermes-inspired: default delivery is the local surface (Command Center),
    not egress. Signal opt-in only records a preview until SIGNAL_LIVE is armed.
    """
    if result.get("dry_run"):
        return None
    channels = list(result.get("channels") or ["command_center"])
    # Always land live runs in the inbox (scheduler or Run now).
    if source != "scheduler" and "command_center" not in channels and "signal" not in channels:
        return None

    signal_preview = None
    if "signal" in channels:
        signal_preview = (
            "would deliver → signal / jon (Signal live not armed; "
            "SOVERYN_AUTOMATIONS_SIGNAL_LIVE=false)"
        )

    content = str(result.get("content") or "")
    if not content and result.get("delivery"):
        content = str((result["delivery"] or {}).get("preview") or "")

    rec = append_inbox(
        automation_id=str(result.get("id") or ""),
        title=str(result.get("title") or result.get("id") or ""),
        agent=str(result.get("agent") or ""),
        channels=channels,
        status=str(result.get("status") or "unknown"),
        content=content,
        session_id=(str(result["session_id"]) if result.get("session_id") else None),
        signal_preview=signal_preview,
        source=source,
        error=(
            str(result["message"])
            if result.get("status") not in ("ok", "would_send") and result.get("message")
            else None
        ),
    )
    return rec


@bp.get("/api/automations")
def api_automations_list():
    """Catalog of scheduled automations + channel prefs."""
    catalog, order = load_automations()
    items = [_spec_to_dict(catalog[i]) for i in order]
    return jsonify({
        "ok": True,
        "version": "v1",
        "dry_run_only": False,
        "signal_live_armed": _SIGNAL_LIVE,
        "available_channels": list(AVAILABLE_CHANNELS),
        "count": len(items),
        "automations": items,
        "fetched_at": datetime.now().isoformat(),
    }), 200


@bp.get("/api/automations/inbox")
def api_automations_inbox():
    """Recent automation runs for the Command Center inbox."""
    try:
        limit = int(request.args.get("limit") or 40)
    except ValueError:
        limit = 40
    items = list_inbox(limit=limit)
    return jsonify({
        "ok": True,
        "count": len(items),
        "inbox": items,
        "signal_live_armed": _SIGNAL_LIVE,
        "fetched_at": datetime.now().isoformat(),
    }), 200


@bp.get("/api/automations/<automation_id>/routine")
def api_automations_routine(automation_id: str):
    """Readable Markdown routine doc (how / when / verify). Overlay wins over package."""
    try:
        get_automation(automation_id)
    except KeyError as exc:
        return jsonify({
            "ok": False,
            "error": "unknown_id",
            "message": str(exc.args[0]),
        }), 404
    doc = load_routine(automation_id)
    if doc is None:
        return jsonify({
            "ok": False,
            "error": "routine_missing",
            "message": f"no routine markdown for {automation_id!r}",
            "id": automation_id,
        }), 404
    return jsonify({
        "ok": True,
        "id": automation_id,
        "source": doc["source"],
        "path": doc["path"],
        "markdown": doc["markdown"],
        "bytes": doc["bytes"],
        "fetched_at": datetime.now().isoformat(),
    }), 200


@bp.put("/api/automations/<automation_id>/channels")
def api_automations_set_channels(automation_id: str):
    """Set delivery channels for one automation (command_center / signal)."""
    try:
        get_automation(automation_id)
    except KeyError as exc:
        return jsonify({
            "ok": False,
            "error": "unknown_id",
            "message": str(exc.args[0]),
        }), 404
    body = request.get_json(silent=True) or {}
    channels = body.get("channels")
    if channels is None and body.get("channel"):
        channels = [body.get("channel")]
    if not isinstance(channels, list):
        return jsonify({
            "ok": False,
            "error": "bad_request",
            "message": "body.channels must be a list (e.g. [\"command_center\", \"signal\"])",
        }), 400
    try:
        saved = set_channels(automation_id, channels)
    except ValueError as exc:
        return jsonify({
            "ok": False,
            "error": "bad_request",
            "message": str(exc),
        }), 400
    return jsonify({
        "ok": True,
        "id": automation_id,
        "channels": saved,
        "available_channels": list(AVAILABLE_CHANNELS),
        "fetched_at": datetime.now().isoformat(),
    }), 200


@bp.post("/api/automations/<automation_id>/run")
def api_automations_run(automation_id: str):
    """Run one automation: dry-run by default, live when ``body.live`` is true.

    Live runs drive the citizen in-process and append a CC inbox row.
    Signal is never sent while signal_live_armed is false.
    """
    body = request.get_json(silent=True) or {}
    live = bool(body.get("live"))
    source = str(body.get("source") or ("scheduler" if body.get("scheduler") else "manual"))
    try:
        spec = get_automation(automation_id)
    except KeyError as exc:
        return jsonify({
            "ok": False,
            "error": "unknown_id",
            "message": str(exc.args[0]),
        }), 404

    agent_loops, conv_store = _in_process_context()
    if live and (agent_loops is None or conv_store is None):
        result = run_automation(automation_id, dry_run=True)
        result["live_requested"] = True
        result["live_fallback"] = "no in-process agent loops; ran dry-run instead"
        return jsonify({
            "ok": result.get("status") == "ok",
            "result": result,
            "fetched_at": datetime.now().isoformat(),
        }), 200

    try:
        result = run_automation(
            automation_id,
            dry_run=not live,
            agent_loop=(agent_loops or {}).get(spec.agent) if live else None,
            conv_store=conv_store if live else None,
        )
    except Exception as exc:  # noqa: BLE001 — live failures must still land in CC inbox
        # Scheduler/Run now must never 500-silent: record the fire + inbox error
        # so Jon sees the miss. Dry-run still raises (preview path is sync/cheap).
        if not live:
            raise
        result = {
            "id": spec.id,
            "title": spec.title,
            "category": spec.category,
            "agent": spec.agent,
            "cron": spec.cron,
            "status": "error",
            "dry_run": False,
            "channels": resolve_channels(spec.id) or ["command_center"],
            "message": f"{type(exc).__name__}: {exc}",
            "content": "",
        }

    inbox_row = None
    if live:
        status = "ok" if result.get("status") == "ok" else "error"
        run_id = None
        if result.get("session_id"):
            run_id = str(result["session_id"])
        record_fire(automation_id, status=status, run_id=run_id)
        inbox_row = _maybe_inbox(result, source=source)

    return jsonify({
        "ok": result.get("status") == "ok",
        "result": result,
        "inbox": inbox_row,
        "signal_live_armed": _SIGNAL_LIVE,
        "fetched_at": datetime.now().isoformat(),
    }), 200
