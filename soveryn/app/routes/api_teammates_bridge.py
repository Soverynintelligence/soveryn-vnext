"""Bridge: Teammates overnight briefs → SOVERYN Messages inbox.

Localhost-only. Teammates stays a separate process/repo (no soveryn import);
it POSTs here after Critic/Scout finish. Findings land as Messages contacts
``t_critic`` / ``t_scout`` — Grok-bot style inboxes, not a second phone app.
"""

from __future__ import annotations

from datetime import datetime

from flask import Blueprint, abort, current_app, jsonify, request

bp = Blueprint("api_teammates_bridge", __name__)

_LOCALHOST_ADDRS = {"127.0.0.1", "::1"}

# Conversation-store agent ids (NOT ACTIVE_AGENTS — read-only overnight inboxes).
# Avoid RETIRED name "scout".
_TEAMMATE_TO_AGENT = {
    "critic": "t_critic",
    "scout": "t_scout",
}

_AGENT_TITLES = {
    "t_critic": "Critic · overnight",
    "t_scout": "Scout · overnight",
}

_MAX_BODY = 6000


def _require_localhost() -> None:
    if request.remote_addr not in _LOCALHOST_ADDRS:
        abort(403, description="teammates bridge requires localhost")


def _state():
    return current_app.extensions["soveryn"]


def _sticky_session(conv_store, agent: str) -> str:
    """Reuse the latest overnight inbox session, or create one."""
    sessions = conv_store.list_sessions(agent=agent, limit=1)
    if sessions:
        return sessions[0].session_id
    return conv_store.new_session(agent, title=_AGENT_TITLES.get(agent, "Teammates"))


@bp.post("/api/internal/teammates_brief")
def teammates_brief():
    """Accept an overnight report and append it to Messages history."""
    _require_localhost()
    body = request.get_json(silent=True) or {}
    teammate_id = str(body.get("teammate_id") or "").strip().lower()
    agent = _TEAMMATE_TO_AGENT.get(teammate_id)
    if not agent:
        return jsonify({"ok": False, "error": f"unknown teammate_id {teammate_id!r}"}), 400

    report = str(body.get("body") or body.get("report") or "").strip()
    summary = str(body.get("summary") or "").strip()
    routine = str(body.get("routine_name") or "").strip()
    status = str(body.get("status") or "").strip() or "ok"
    run_id = str(body.get("run_id") or "").strip()

    if not report and not summary:
        return jsonify({"ok": False, "error": "body or summary required"}), 400

    conv_store = _state().get("conv_store")
    if conv_store is None:
        return jsonify({"ok": False, "error": "conv_store unavailable"}), 503

    text = report or summary
    if len(text) > _MAX_BODY:
        text = text[:_MAX_BODY] + "\n\n…[truncated for Messages]"

    header = f"**{teammate_id.title()} overnight**"
    if routine:
        header += f" · `{routine}`"
    if status:
        header += f" · {status}"
    if run_id:
        header += f"\n`run {run_id[:8]}…`"
    bubble = f"{header}\n\n{text}"

    session_id = _sticky_session(conv_store, agent)
    # Touch title so the list preview stays meaningful
    try:
        with conv_store._conn() as conn:
            conn.execute(
                "UPDATE conversation_meta SET title = ?, updated_at = ?"
                " WHERE session_id = ?",
                (
                    _AGENT_TITLES.get(agent, "Teammates"),
                    datetime.now().isoformat(),
                    session_id,
                ),
            )
    except Exception:
        pass

    conv_store.save_turn(
        session_id,
        agent,
        "assistant",
        bubble,
        source="teammates_overnight",
    )
    return jsonify({
        "ok": True,
        "agent": agent,
        "session_id": session_id,
        "chars": len(bubble),
    })
