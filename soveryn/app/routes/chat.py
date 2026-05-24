"""SOVERYN vNext — chat + session routes.

Sync /chat only (no SSE). No persona, no tools, no memory recall.
Stable machine-readable error codes (see soveryn/app/startup.py).
"""

from __future__ import annotations
from flask import Blueprint, current_app, jsonify, request

from soveryn.agents.loop import AgentLoop, AgentLoopError
from soveryn.config.runtime import ACTIVE_AGENTS, RETIRED
from soveryn.inference.llama_server_client import LlamaServerError, LlamaServerTimeout
from soveryn.inference.routing import RoutingError

bp = Blueprint("chat", __name__)


# ─── Small helpers (route-local, deliberately not abstracted further) ────────

def _err(code: str, message: str, status: int):
    return jsonify({"error": {"code": code, "message": message}}), status


def _parse_json_body():
    """Return parsed dict or an error tuple. Use: body, err = _parse_json_body()."""
    if request.content_type and "application/json" not in request.content_type.lower():
        return None, _err("invalid_json",
                          f"Content-Type must be application/json (got {request.content_type!r})",
                          400)
    body = request.get_json(silent=True)
    if body is None or not isinstance(body, dict):
        return None, _err("invalid_json", "Request body must be a JSON object", 400)
    return body, None


def _resolve_agent(name: str | None):
    """Return (normalized_name, None) or (None, error_response)."""
    if not isinstance(name, str) or not name.strip():
        return None, _err("missing_field", "Required field: agent", 400)
    n = name.lower().strip()
    if n in RETIRED:
        return None, _err("retired_agent",
                          f"Agent {n!r} is retired and cannot be reached", 400)
    if n not in ACTIVE_AGENTS:
        return None, _err("unknown_agent",
                          f"Agent {n!r} is not active. Active: {sorted(ACTIVE_AGENTS)}", 400)
    return n, None


def _state():
    return current_app.extensions["soveryn"]


# ─── /sessions CRUD ──────────────────────────────────────────────────────────

@bp.post("/sessions")
def create_session():
    body, err = _parse_json_body()
    if err:
        return err
    agent, err = _resolve_agent(body.get("agent"))
    if err:
        return err
    title = body.get("title")
    if title is not None and not isinstance(title, str):
        return _err("invalid_message", "title must be a string or omitted", 400)
    sid = _state()["conv_store"].new_session(agent, title=title)
    return jsonify({"session_id": sid, "agent": agent, "title": title}), 201


@bp.get("/sessions")
def list_sessions():
    agent_param = request.args.get("agent")
    if agent_param is not None:
        agent, err = _resolve_agent(agent_param)
        if err:
            return err
    else:
        agent = None
    try:
        limit = int(request.args.get("limit", "100"))
    except ValueError:
        return _err("invalid_message", "limit must be an integer", 400)
    sessions = _state()["conv_store"].list_sessions(agent=agent, limit=limit)
    return jsonify({
        "sessions": [
            {
                "session_id": s.session_id,
                "agent": s.agent,
                "title": s.title,
                "created_at": s.created_at,
                "updated_at": s.updated_at,
            }
            for s in sessions
        ],
    }), 200


@bp.get("/sessions/<session_id>/history")
def get_history(session_id: str):
    conv = _state()["conv_store"]
    session = conv.get_session(session_id)
    if session is None:
        return _err("missing_session", f"No session {session_id!r}", 404)
    history = conv.load_history(session_id)
    return jsonify({
        "session_id": session_id,
        "agent": session.agent,
        "turns": [
            {"role": t.role, "content": t.content, "timestamp": t.timestamp, "source": t.source}
            for t in history
        ],
    }), 200


@bp.delete("/sessions/<session_id>")
def delete_session(session_id: str):
    conv = _state()["conv_store"]
    session = conv.get_session(session_id)
    if session is None:
        return _err("missing_session", f"No session {session_id!r}", 404)
    conv.delete_session(session_id)
    return jsonify({"deleted": session_id}), 200


# ─── /chat (sync) ────────────────────────────────────────────────────────────

@bp.post("/chat")
def chat():
    body, err = _parse_json_body()
    if err:
        return err

    agent, err = _resolve_agent(body.get("agent"))
    if err:
        return err

    session_id = body.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        return _err("missing_field", "Required field: session_id", 400)

    message = body.get("message")
    if not isinstance(message, str) or not message.strip():
        return _err("invalid_message", "message must be a non-empty string", 400)

    state = _state()
    loop = state["agent_loops"].get(agent)
    if loop is None:
        # Defense in depth: agent_loops should always have every ACTIVE_AGENT.
        return _err("unknown_agent", f"No loop registered for {agent!r}", 400)

    # AgentLoop validates session ownership BEFORE chat; we translate its
    # AgentLoopError into the right HTTP status here.
    try:
        response = loop.process_message(session_id, message)
    except AgentLoopError as e:
        msg = str(e)
        if "does not exist" in msg:
            return _err("missing_session", msg, 404)
        if "belongs to agent" in msg:
            return _err("session_agent_mismatch", msg, 409)
        return _err("internal_error", msg, 500)
    except LlamaServerTimeout as e:
        return _err("chat_timeout", str(e), 504)
    except LlamaServerError as e:
        return _err("chat_server_error", str(e), 502)
    except RoutingError as e:
        # Shouldn't happen for an active agent, but be honest if it does.
        return _err("unknown_agent", str(e), 400)

    return jsonify({
        "agent": agent,
        "session_id": session_id,
        "content": response.content,
        "finish_reason": response.finish_reason,
        "tool_calls": list(response.tool_calls) if response.tool_calls else None,
        "usage": response.usage,
    }), 200
