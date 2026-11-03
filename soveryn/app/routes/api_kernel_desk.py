"""/api/kernel/* — the Desk's Kernel thread (Pi RPC over SSE).

Every route is operator-local only: a direct loopback socket WITHOUT the
public-gate edge mark (soveryn.edge.is_operator_local). Funneled requests are
refused even though they arrive from 127.0.0.1. POSTs also need the per-boot
CSRF token (X-Kernel-CSRF) and, when the browser sends one, a same-host Origin.
"""
from __future__ import annotations

import json
import queue
import secrets
from urllib.parse import urlparse

from flask import Blueprint, Response, abort, jsonify, request, stream_with_context

from soveryn.edge import is_operator_local
from soveryn.kernel_desk import lease
from soveryn.kernel_desk.manager import (
    MANAGER, find_session_file, list_sessions, read_history, resume_command, sessions_root,
)

bp = Blueprint("api_kernel_desk", __name__)

CSRF_TOKEN = secrets.token_urlsafe(32)
_MAX_MSG = 20000


@bp.before_request
def _guard():
    if not is_operator_local(request.remote_addr, request.headers):
        abort(403, description="kernel desk is operator-local only")
    if request.method != "GET":
        if not secrets.compare_digest(request.headers.get("X-Kernel-CSRF", ""), CSRF_TOKEN):
            abort(403, description="missing or bad CSRF token")
        origin = request.headers.get("Origin")
        if origin and urlparse(origin).netloc != request.host:
            abort(403, description="cross-origin request refused")


def _sid_ok(sid: str) -> str:
    if not sid or len(sid) > 120 or not all(c.isalnum() or c in "._-" for c in sid):
        abort(400, description="bad session id")
    return sid


@bp.get("/api/kernel/csrf")
def csrf():
    resp = jsonify({"token": CSRF_TOKEN})
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.get("/api/kernel/threads")
def threads():
    rows = list_sessions(limit=int(request.args.get("limit", 30)))
    for r in rows:
        r["open_in_desk"] = MANAGER.get(r["id"]) is not None
    return jsonify({"threads": rows, "sessions_root": str(sessions_root())})


@bp.post("/api/kernel/threads")
def new_thread():
    try:
        t = MANAGER.open(None)
    except lease.LeaseHeld as e:
        return jsonify({"ok": False, "error": str(e), "lease": e.lease}), 409
    return jsonify({"ok": True, "session_id": t.sid})


@bp.post("/api/kernel/threads/<sid>/open")
def open_thread(sid):
    _sid_ok(sid)
    try:
        t = MANAGER.open(sid)
    except FileNotFoundError:
        return jsonify({"ok": False, "error": "no such session"}), 404
    except lease.LeaseHeld as e:
        return jsonify({"ok": False, "error": str(e), "lease": e.lease}), 409
    return jsonify({"ok": True, "session_id": t.sid})


@bp.get("/api/kernel/threads/<sid>")
def thread_info(sid):
    _sid_ok(sid)
    p = find_session_file(sid)
    if p is None and MANAGER.get(sid) is None:
        return jsonify({"ok": False, "error": "no such session"}), 404
    return jsonify({"ok": True, "session_id": sid, "path": str(p) if p else None,
                    "open_in_desk": MANAGER.get(sid) is not None,
                    "lease": lease.status(sessions_root(), sid),
                    "resume": resume_command(sid)})


@bp.get("/api/kernel/threads/<sid>/messages")
def thread_messages(sid):
    _sid_ok(sid)
    return jsonify({"session_id": sid, "messages": read_history(sid)})


def _cmd(sid: str, body: dict):
    t = MANAGER.get(_sid_ok(sid))
    if t is None:
        return jsonify({"ok": False, "error": "thread not open in desk"}), 409
    cid = t.send(body)
    return jsonify({"ok": True, "id": cid})


@bp.post("/api/kernel/threads/<sid>/prompt")
def prompt(sid):
    body = request.get_json(silent=True) or {}
    msg = str(body.get("message") or "").strip()
    if not msg or len(msg) > _MAX_MSG:
        return jsonify({"ok": False, "error": "message required (max 20000 chars)"}), 400
    mode = body.get("mode")
    cmd = {"type": "prompt", "message": msg}
    if mode in ("steer", "followUp"):
        cmd["streamingBehavior"] = mode
    return _cmd(sid, cmd)


@bp.post("/api/kernel/threads/<sid>/abort")
def abort_run(sid):
    return _cmd(sid, {"type": "abort"})


@bp.post("/api/kernel/threads/<sid>/release")
def release(sid):
    """Hand to CLI: stop the Desk's writer and free the lease."""
    _sid_ok(sid)
    return jsonify(MANAGER.release(sid))


@bp.get("/api/kernel/threads/<sid>/events")
def events(sid):
    _sid_ok(sid)
    t = MANAGER.get(sid)
    if t is None:
        return jsonify({"ok": False, "error": "thread not open in desk"}), 409
    try:
        since = int(request.headers.get("Last-Event-ID") or request.args.get("since") or 0)
    except ValueError:
        since = 0
    q, backlog = t.subscribe(since)

    def gen():
        try:
            yield "retry: 2000\n\n"
            for seq, rec in backlog:
                yield f"id: {seq}\ndata: {json.dumps(rec)}\n\n"
            while True:
                try:
                    seq, rec = q.get(timeout=15)
                except queue.Empty:
                    yield ": keepalive\n\n"
                    if not t.alive():
                        return
                    continue
                yield f"id: {seq}\ndata: {json.dumps(rec)}\n\n"
                if rec.get("type") == "desk_exit":
                    return
        finally:
            t.unsubscribe(q)

    return Response(stream_with_context(gen()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
