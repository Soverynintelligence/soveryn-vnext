"""Bridge: Kernel CLI status/receipts → SOVERYN Messages (Kernel thread).

Localhost-only. Mirrors teammates overnight bridge: append an assistant
bubble to Kernel's sticky Messages session + optional Web Push.
Phone-origin privilege is NOT granted — this is outbound status only.
"""

from __future__ import annotations

from datetime import datetime

from flask import Blueprint, abort, current_app, jsonify, request

bp = Blueprint("api_kernel_bridge", __name__)

_LOCALHOST_ADDRS = {"127.0.0.1", "::1"}
_MAX_BODY = 6000
_AGENT = "kernel"
_TITLE = "Kernel · CLI"


def _require_localhost() -> None:
    if request.remote_addr not in _LOCALHOST_ADDRS:
        abort(403, description="kernel bridge requires localhost")


def _state():
    return current_app.extensions["soveryn"]


def _sticky_session(conv_store) -> str:
    sessions = conv_store.list_sessions(agent=_AGENT, limit=1)
    if sessions:
        return sessions[0].session_id
    return conv_store.new_session(_AGENT, title=_TITLE)


@bp.post("/api/internal/kernel_cli_receipt")
def kernel_cli_receipt():
    """Accept a CLI receipt/status and append it to Kernel Messages history."""
    _require_localhost()
    body = request.get_json(silent=True) or {}

    text = str(body.get("body") or body.get("report") or body.get("text") or "").strip()
    summary = str(body.get("summary") or "").strip()
    run_id = str(body.get("run_id") or "").strip()
    action = str(body.get("action") or "receipt").strip() or "receipt"
    ok_raw = body.get("ok")
    finish_reason = str(body.get("finish_reason") or "").strip()
    verdict = body.get("verdict")

    if not text and not summary and not verdict:
        return jsonify({"ok": False, "error": "body, summary, or verdict required"}), 400

    # tool_round_limit must never present as success
    if finish_reason in {"tool_round_limit", "tool_round_limit_hit"}:
        ok_raw = False
    if isinstance(verdict, list):
        verdict_block = "\n".join(str(v) for v in verdict)
    else:
        verdict_block = str(verdict or "").strip()

    payload = text or summary or verdict_block
    if len(payload) > _MAX_BODY:
        payload = payload[:_MAX_BODY] + "\n\n…[truncated for Messages]"

    status = "ok" if ok_raw is True else ("fail" if ok_raw is False else "note")
    if finish_reason in {"tool_round_limit", "tool_round_limit_hit"}:
        status = "fail · tool_round_limit (not success)"

    header = f"**Kernel CLI · `{action}`** · {status}"
    if run_id:
        header += f"\n`run {run_id}`"
    if finish_reason and finish_reason not in status:
        header += f"\n`finish_reason={finish_reason}`"

    parts = [header]
    if verdict_block and verdict_block != payload:
        parts.append(verdict_block)
    parts.append(payload)
    bubble = "\n\n".join(parts)

    conv_store = _state().get("conv_store")
    if conv_store is None:
        return jsonify({"ok": False, "error": "conv_store unavailable"}), 503

    session_id = _sticky_session(conv_store)
    try:
        with conv_store._conn() as conn:
            conn.execute(
                "UPDATE conversation_meta SET title = ?, updated_at = ?"
                " WHERE session_id = ?",
                (_TITLE, datetime.now().isoformat(), session_id),
            )
    except Exception:
        pass

    conv_store.save_turn(
        session_id,
        _AGENT,
        "assistant",
        bubble,
        source="kernel_cli",
        finish_reason=finish_reason or None,
    )

    try:
        from soveryn.platform.webpush.notify import notify_needs_you

        notify_needs_you(
            title="Kernel CLI",
            body=(summary or action)[:120],
            url="/messages/kernel",
            tag="kernel-cli-receipt",
        )
    except Exception:
        pass

    return jsonify({
        "ok": True,
        "agent": _AGENT,
        "session_id": session_id,
        "chars": len(bubble),
        "status": status,
    })
