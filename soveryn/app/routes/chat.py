"""SOVERYN vNext — chat + session routes.

Sync /chat and streaming /chat_stream (SSE). No persona, no tools, no memory recall.
Stable machine-readable error codes (see soveryn/app/startup.py).
"""

from __future__ import annotations
import json as _json
from flask import Blueprint, Response, current_app, jsonify, request, stream_with_context

from soveryn.agents.loop import (
    AgentLoop, AgentLoopError, AgentStreamEvent, DoneEvent, ErrorEvent, TokenEvent,
    ToolCallEvent, ToolResultEvent,
)
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


# ─── /chat_stream (SSE streaming) ────────────────────────────────────────────

def _sse(payload: dict) -> str:
    """Format one SSE event line."""
    return f"data: {_json.dumps(payload, ensure_ascii=False)}\n\n"


def _event_to_dict(event: AgentStreamEvent) -> dict:
    if isinstance(event, TokenEvent):
        return {"type": "token", "delta": event.delta}
    if isinstance(event, DoneEvent):
        return {
            "type": "done",
            "content": event.content,
            "finish_reason": event.finish_reason,
            "tool_calls": list(event.tool_calls) if event.tool_calls else None,
            "usage": event.usage,
        }
    if isinstance(event, ErrorEvent):
        return {"type": "error", "code": event.code, "message": event.message}
    if isinstance(event, ToolCallEvent):
        return {
            "type": "tool_call",
            "call_id": event.call_id,
            "name": event.name,
            "args": event.args,
        }
    if isinstance(event, ToolResultEvent):
        return {
            "type": "tool_result",
            "call_id": event.call_id,
            "name": event.name,
            "content": event.content,
            "channel": event.channel,
        }
    # Defensive — shouldn't happen with the union closed
    return {"type": "error", "code": "internal_error",
            "message": f"unknown event type {type(event).__name__}"}


@bp.post("/chat_stream")
def chat_stream():
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
        return _err("unknown_agent", f"No loop registered for {agent!r}", 400)

    # ── Open the AgentLoop stream and pump the first chunk *before* returning
    # the SSE Response. This lets setup errors (session mismatch, recall
    # failure, upstream HTTP error before any chunk) translate to JSON 4xx/5xx
    # per constraint 3, rather than appearing inside a half-opened text/event-stream.
    try:
        event_iter = loop.process_message_stream(session_id, message)
        # Pre-fetch the first event so setup errors surface here.
        try:
            first_event = next(event_iter)
        except StopIteration:
            # Generator returned without yielding anything (shouldn't happen on
            # success; AgentLoop always yields at least a DoneEvent or ErrorEvent).
            return _err("internal_error", "AgentLoop yielded no events", 500)
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
        return _err("unknown_agent", str(e), 400)
    except Exception as e:
        return _err("chat_server_error", f"{type(e).__name__}: {e}", 502)

    # ── Setup OK. Now wrap the iterator in an SSE response.
    def _generate():
        # First event was already pulled — emit it.
        yield _sse(_event_to_dict(first_event))
        for event in event_iter:
            yield _sse(_event_to_dict(event))

    return Response(
        stream_with_context(_generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Content-Type": "text/event-stream; charset=utf-8",
        },
    )
