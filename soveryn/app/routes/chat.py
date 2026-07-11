"""SOVERYN vNext — chat + session routes.

Sync /chat and streaming /chat_stream (SSE). No persona, no tools, no memory recall.
Stable machine-readable error codes (see soveryn/app/startup.py).
"""

from __future__ import annotations
import json as _json
from datetime import datetime
from flask import Blueprint, Response, current_app, jsonify, request, stream_with_context

from soveryn.agents.loop import (
    AgentLoop, AgentLoopError, AgentStreamEvent, DoneEvent, ErrorEvent, TokenEvent,
    ToolCallEvent, ToolResultEvent, TTSTokenEvent,
)
from soveryn.agents.presence.resolver import ResolveResult, resolve_pending
from soveryn.config.runtime import ACTIVE_AGENTS, RETIRED
from soveryn.inference.llama_server_client import LlamaServerError, LlamaServerTimeout
from soveryn.inference.routing import RoutingError

bp = Blueprint("chat", __name__)


# Vision attachments — accepted at /chat + /chat_stream, plumbed to AgentLoop.
# The MIME set is canonicalized in soveryn.platform.vision_types so the
# route, the signal-bridge encoder, and the UI's file-input accept all
# derive from one source. See vision_types.py + the parity test in
# tests/test_vision_types_parity.py.
from soveryn.platform.vision_types import ALLOWED_IMAGE_MIME_PREFIXES  # noqa: E402

# ~25MB pre-decode ceiling (base64 expands ~4/3 → ~25MB binary). Bounded at
# the route boundary so a malformed client can't OOM the loop or the wire.
MAX_ATTACHMENT_DATA_URL_BYTES = 33_000_000


# ─── Small helpers (route-local, deliberately not abstracted further) ────────

def _err(code: str, message: str, status: int):
    return jsonify({"error": {"code": code, "message": message}}), status


def _validate_attachments(raw, agent: str):
    """Validate and normalize the optional 'attachments' field.

    Returns: (attachments_tuple_or_none, error_response_or_none).
    On success: (None | tuple[str, ...], None).
    On failure: (None, (jsonified_err, status_code)).

    Empty list is treated as absent (returns None) — the AgentLoop's
    `if attachments:` truthiness gate then bypasses the vision splice.
    """
    if raw is None:
        return None, None
    if not isinstance(raw, list):
        return None, _err("invalid_attachments",
                          "attachments must be a list of data: URL strings", 400)
    if not raw:  # empty list — treat as absent
        return None, None
    for a in raw:
        if not isinstance(a, str):
            return None, _err("invalid_attachments",
                              f"attachment entries must be strings, got {type(a).__name__}",
                              400)
        if not a.startswith(ALLOWED_IMAGE_MIME_PREFIXES):
            return None, _err("invalid_attachments",
                              "only data:image/{jpeg,png,webp,gif} URLs accepted", 400)
        if len(a) > MAX_ATTACHMENT_DATA_URL_BYTES:
            return None, _err("invalid_attachments",
                              f"attachment exceeds {MAX_ATTACHMENT_DATA_URL_BYTES} bytes", 400)
    if agent != "aetheria":
        return None, _err("agent_does_not_support_vision",
                          f"agent {agent!r} has no vision model loaded", 400)
    return tuple(raw), None


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


def maybe_resolve_x_approval(
    *, agent: str, message: str, state: dict, now: str,
) -> ResolveResult | None:
    """Pre-turn hook: resolve a pending staged X post against `message`.

    Called from BOTH /chat and /chat_stream, before the AgentLoop turn — a
    hook in only one route would be bypassed by whichever surface uses the
    other (the desktop UI streams). Staged posts are keyed on the AGENT
    ("aetheria"), not session_id, so this fires regardless of which session
    Jon replies in — a post proposed during a heartbeat wake (session
    `[heartbeat] aetheria`) can be approved from his primary thread.

    Returns None (caller proceeds into the normal turn unchanged) when:
      - `agent != "aetheria"` (the only agent with an X presence),
      - the X deps aren't wired on `state` (e.g. a test/fixture app that
        never populated app.extensions["soveryn"] — fail open, not KeyError),
      - there's nothing staged, or `message` doesn't classify as a clear
        affirm/decline (unrelated, edit, or a [HEARTBEAT] brief — classify
        buckets those as "unrelated" with no special-casing needed here).

    Returns a ResolveResult only on a clear affirm (published) or decline
    (rejected) — the caller must return that outcome to the client and
    skip the agent's normal turn (a bare affirm's whole meaning was "post
    it"; running her normal turn on top would be a non sequitur).
    """
    if agent != "aetheria":
        return None

    x_staged = state.get("x_staged")
    x_publisher_fn = state.get("x_publisher_fn")
    x_memory_fn = state.get("x_memory_fn")
    x_rejection_fn = state.get("x_rejection_fn")
    if x_staged is None or x_publisher_fn is None or x_memory_fn is None or x_rejection_fn is None:
        return None

    return resolve_pending(
        agent="aetheria",
        message=message,
        staged=x_staged,
        publisher_fn=x_publisher_fn,
        x_memory_fn=x_memory_fn,
        rejection_fn=x_rejection_fn,
        now=now,
    )


def _x_resolution_payload(result: ResolveResult) -> dict:
    return {
        "action": result.action,
        "note": result.note,
        "posted_id": result.posted_id,
    }


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

    attachments, attach_err = _validate_attachments(body.get("attachments"), agent)
    if attach_err is not None:
        return attach_err

    state = _state()

    # X-approval pre-turn hook (Task 8) — before the loop. A clear affirm/
    # decline on a staged post resolves it here and returns without running
    # the normal turn; anything else (nothing staged, unrelated, edit, a
    # [HEARTBEAT] brief, or agent != aetheria) is a no-op and falls through.
    x_result = maybe_resolve_x_approval(
        agent=agent, message=message, state=state, now=datetime.now().isoformat(),
    )
    if x_result is not None:
        return jsonify({
            "agent": agent,
            "session_id": session_id,
            "x_resolution": _x_resolution_payload(x_result),
        }), 200

    loop = state["agent_loops"].get(agent)
    if loop is None:
        # Defense in depth: agent_loops should always have every ACTIVE_AGENT.
        return _err("unknown_agent", f"No loop registered for {agent!r}", 400)

    # AgentLoop validates session ownership BEFORE chat; we translate its
    # AgentLoopError into the right HTTP status here.
    try:
        response = loop.process_message(session_id, message, attachments=attachments)
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
        "context_usage": response.context_usage,
    }), 200


# ─── /chat_stream (SSE streaming) ────────────────────────────────────────────

def _sse(payload: dict) -> str:
    """Format one SSE event line."""
    return f"data: {_json.dumps(payload, ensure_ascii=False)}\n\n"


def _event_to_dict(event: AgentStreamEvent) -> dict | None:
    if isinstance(event, TokenEvent):
        return {"type": "token", "delta": event.delta}
    if isinstance(event, TTSTokenEvent):
        # Voice-only event — the chat SSE channel doesn't surface it. Returning
        # None signals the SSE generator to skip without emitting a frame.
        return None
    if isinstance(event, DoneEvent):
        return {
            "type": "done",
            "content": event.content,
            "finish_reason": event.finish_reason,
            "tool_calls": list(event.tool_calls) if event.tool_calls else None,
            "usage": event.usage,
            "context_usage": event.context_usage,
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

    attachments, attach_err = _validate_attachments(body.get("attachments"), agent)
    if attach_err is not None:
        return attach_err

    state = _state()

    # X-approval pre-turn hook (Task 8) — same helper as /chat, called BEFORE
    # the loop here too. A hook in only /chat would be bypassed by the
    # desktop UI, which streams. See maybe_resolve_x_approval's docstring.
    x_result = maybe_resolve_x_approval(
        agent=agent, message=message, state=state, now=datetime.now().isoformat(),
    )
    if x_result is not None:
        def _generate_x_resolution():
            yield _sse({"type": "x_resolution", **_x_resolution_payload(x_result)})

        return Response(
            stream_with_context(_generate_x_resolution()),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Content-Type": "text/event-stream; charset=utf-8",
            },
        )

    loop = state["agent_loops"].get(agent)
    if loop is None:
        return _err("unknown_agent", f"No loop registered for {agent!r}", 400)

    # ── Open the AgentLoop stream and pump the first chunk *before* returning
    # the SSE Response. This lets setup errors (session mismatch, recall
    # failure, upstream HTTP error before any chunk) translate to JSON 4xx/5xx
    # per constraint 3, rather than appearing inside a half-opened text/event-stream.
    try:
        event_iter = loop.process_message_stream(session_id, message, attachments=attachments)
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
        # First event was already pulled — emit it (skip if voice-only).
        first_payload = _event_to_dict(first_event)
        if first_payload is not None:
            yield _sse(first_payload)
        for event in event_iter:
            payload = _event_to_dict(event)
            if payload is not None:
                yield _sse(payload)

    return Response(
        stream_with_context(_generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Content-Type": "text/event-stream; charset=utf-8",
        },
    )
