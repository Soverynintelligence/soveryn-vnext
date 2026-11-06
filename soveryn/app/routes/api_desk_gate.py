"""/api/desk-gate/* + /desk-gate page — Jon approves/denies Desk Kernel dangerous calls.

Operator-local only (soveryn.edge.is_operator_local; Funnel requests refused).
/check and /status are called by the Desk's Pi child with X-Desk-Gate-Token.
/decide needs the page's per-boot CSRF token. No new port, no Funnel route.
"""
from __future__ import annotations

import secrets
from urllib.parse import urlparse

from flask import Blueprint, abort, jsonify, render_template, request

from soveryn.edge import is_operator_local
from soveryn.kernel_desk import gate
from soveryn.kernel_desk.danger import classify
from soveryn.paths import SoverynPaths

bp = Blueprint("api_desk_gate", __name__)
CSRF = secrets.token_urlsafe(32)


@bp.before_request
def _guard():
    if not is_operator_local(request.remote_addr, request.headers):
        abort(403, description="desk gate is operator-local only")


def _need_token():
    if not secrets.compare_digest(request.headers.get("X-Desk-Gate-Token", ""), gate.GATE_TOKEN):
        abort(403, description="bad gate token")


@bp.post("/api/desk-gate/check")
def check():
    _need_token()
    b = request.get_json(silent=True) or {}
    tool = str(b.get("tool") or "")
    args = b.get("args") if isinstance(b.get("args"), dict) else {}
    cwd = str(b.get("cwd") or "") or None
    v = classify(tool, args, SoverynPaths.root(), cwd=cwd)
    if not v.dangerous:
        return jsonify({"action": "allow"})
    row = gate.create(tool, args, cwd or "", str(b.get("session") or ""), v.rule, v.reason)
    return jsonify({"action": "hold", "id": row["id"], "rule": v.rule, "reason": v.reason}), 202


@bp.get("/api/desk-gate/status/<gid>")
def status(gid):
    _need_token()
    row = gate.consume(gid)
    if row is None:
        abort(404)
    return jsonify({"id": gid, "status": row["status"], "consumed": bool(row.get("consumed"))})


@bp.get("/api/desk-gate/list")
def list_():
    return jsonify({"items": gate.list_recent(), "csrf": CSRF})


@bp.post("/api/desk-gate/decide/<gid>")
def decide(gid):
    if not secrets.compare_digest(request.headers.get("X-Desk-Gate-CSRF", ""), CSRF):
        abort(403, description="missing or bad CSRF token")
    origin = request.headers.get("Origin")
    if origin and urlparse(origin).netloc != request.host:
        abort(403, description="cross-origin request refused")
    d = (request.get_json(silent=True) or {}).get("decision")
    try:
        row = gate.decide(gid, d)
    except ValueError as e:
        abort(400, description=str(e))
    if row is None:
        abort(409, description="not pending (already decided or expired)")
    return jsonify(row)


@bp.get("/desk-gate")
def page():
    # Desk house style: same five-door nav as every other Desk page.
    from soveryn.app.routes.ui import apply_sd_nav
    return apply_sd_nav(render_template("desk_gate.html"))
