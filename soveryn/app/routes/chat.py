"""SOVERYN vNext — chat + session routes.

Sync /chat and streaming /chat_stream (SSE). No persona, no tools, no memory recall.
Stable machine-readable error codes (see soveryn/app/startup.py).
"""

from __future__ import annotations
import json as _json
from datetime import datetime
from flask import Blueprint, Response, current_app, jsonify, request, stream_with_context

from soveryn.agents.loop import (
    AgentLoop, AgentLoopError, AgentStreamEvent, ApprovalPendingEvent,
    DoneEvent, ErrorEvent, TokenEvent,
    ToolCallEvent, ToolResultEvent, TTSTokenEvent,
)
from soveryn.agents.presence.resolver import ResolveResult, resolve_pending
from soveryn.config.runtime import ACTIVE_AGENTS, RETIRED
from soveryn.inference.llama_server_client import LlamaServerError, LlamaServerTimeout
from soveryn.inference.routing import RoutingError

bp = Blueprint("chat", __name__)

# Teammates overnight → Messages inboxes (read-only; not chattable agents).
INBOX_AGENTS: frozenset[str] = frozenset({"t_critic", "t_scout"})


# Vision attachments — accepted at /chat + /chat_stream, plumbed to AgentLoop.
# The MIME set is canonicalized in soveryn.platform.vision_types so the
# route, the signal-bridge encoder, and the UI's file-input accept all
# derive from one source. See vision_types.py + the parity test in
# tests/test_vision_types_parity.py.
from soveryn.platform.vision_types import (  # noqa: E402
    ALLOWED_IMAGE_MIME_PREFIXES,
    VISION_CAPABLE_AGENTS,
)

# ~25MB pre-decode ceiling (base64 expands ~4/3 → ~25MB binary). Bounded at
# the route boundary so a malformed client can't OOM the loop or the wire.
MAX_ATTACHMENT_DATA_URL_BYTES = 33_000_000

_PDF_DATA_PREFIX = "data:application/pdf"


# ─── Small helpers (route-local, deliberately not abstracted further) ────────

def _err(code: str, message: str, status: int):
    return jsonify({"error": {"code": code, "message": message}}), status


def _validate_attachments(raw, agent: str):
    """Validate attachments: images (vision) and/or PDFs (intake text splice).

    Returns: ``(images, pdfs, error)`` where
      - images: ``None | tuple[str, ...]`` data:image URLs for AgentLoop vision
      - pdfs: ``tuple[str, ...]`` data:application/pdf URLs (extracted before turn)
      - error: Flask error response or None

    Empty list is treated as absent. Images still require a vision-capable
    agent; PDF-only attachments are allowed for any active agent.
    """
    if raw is None:
        return None, (), None
    if not isinstance(raw, list):
        return None, (), _err(
            "invalid_attachments",
            "attachments must be a list of data: URL strings",
            400,
        )
    if not raw:
        return None, (), None

    images: list[str] = []
    pdfs: list[str] = []
    for a in raw:
        if not isinstance(a, str):
            return None, (), _err(
                "invalid_attachments",
                f"attachment entries must be strings, got {type(a).__name__}",
                400,
            )
        if len(a) > MAX_ATTACHMENT_DATA_URL_BYTES:
            return None, (), _err(
                "invalid_attachments",
                f"attachment exceeds {MAX_ATTACHMENT_DATA_URL_BYTES} bytes",
                400,
            )
        if a.startswith(ALLOWED_IMAGE_MIME_PREFIXES):
            images.append(a)
        elif a.startswith(_PDF_DATA_PREFIX):
            pdfs.append(a)
        else:
            return None, (), _err(
                "invalid_attachments",
                "only data:image/{jpeg,png,webp,gif} or data:application/pdf URLs accepted",
                400,
            )

    if images and agent not in VISION_CAPABLE_AGENTS:
        return None, (), _err(
            "agent_does_not_support_vision",
            f"agent {agent!r} has no vision model loaded",
            400,
        )
    return (tuple(images) if images else None), tuple(pdfs), None


def _splice_pdf_attachments(message: str, pdf_data_urls: tuple[str, ...]) -> str:
    """Extract text-layer PDFs and prepend intake blocks to the user message."""
    if not pdf_data_urls:
        return message
    import base64
    import re

    from soveryn.platform.intake.pdf import extract_pdf_bytes, splice_into_message

    results = []
    for i, url in enumerate(pdf_data_urls):
        m = re.match(r"^data:application/pdf(;[^,]*)?,", url)
        if not m:
            continue
        b64 = url.split(",", 1)[-1]
        try:
            data = base64.b64decode(b64, validate=False)
        except Exception as exc:  # noqa: BLE001
            from soveryn.platform.intake.pdf import ExtractResult

            results.append(
                ExtractResult(
                    status="failed",
                    text="",
                    page_count=0,
                    pages_with_text=0,
                    chars=0,
                    gap=f"base64 decode failed: {exc}",
                    source_name=f"attachment-{i + 1}.pdf",
                )
            )
            continue
        results.append(
            extract_pdf_bytes(data, source_name=f"attachment-{i + 1}.pdf")
        )
    return splice_into_message(message, results)


def _validate_source(raw):
    """Validate the optional 'source' field.

    Returns: (source_str, error_response_or_none). Absent → ("direct", None)
    — this is the human-chat default at every layer (AgentLoop, save_turn).
    Present but not a non-empty str → 400. The heartbeat daemon is the only
    caller that opts into a non-default value ("heartbeat").
    """
    if raw is None:
        return "direct", None
    if not isinstance(raw, str) or not raw.strip():
        return None, _err("invalid_source",
                          "source must be a non-empty string", 400)
    return raw, None


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


def _resolve_agent_or_inbox(name: str | None):
    """Like _resolve_agent, but allows Teammates overnight inbox ids for /sessions."""
    if not isinstance(name, str) or not name.strip():
        return None, _err("missing_field", "Required field: agent", 400)
    n = name.lower().strip()
    if n in INBOX_AGENTS:
        return n, None
    return _resolve_agent(name)


def _state():
    return current_app.extensions["soveryn"]


def maybe_resolve_x_approval(
    *, agent: str, message: str, state: dict, now: str,
) -> ResolveResult | None:
    """Pre-turn hook: resolve a pending staged X post against `message`.

    Called from BOTH /chat and /chat_stream, before the AgentLoop turn — a
    hook in only one route would be bypassed by whichever surface uses the
    other (the desktop UI streams). Staged posts are keyed on the AGENT
    (eve), not session_id. Approve from Eve's Messages thread with "post it".

    Returns None (caller proceeds into the normal turn unchanged) when:
      - `agent` is not Eve (Aetheria is off X),
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
    if agent != "eve":
        return None

    x_staged = state.get("x_staged")
    x_publisher_fn = state.get("x_publisher_fn")
    x_memory_fn = state.get("x_memory_fn")
    x_rejection_fn = state.get("x_rejection_fn")
    if x_staged is None or x_publisher_fn is None or x_memory_fn is None or x_rejection_fn is None:
        return None

    return resolve_pending(
        agent=agent,
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
        agent, err = _resolve_agent_or_inbox(agent_param)
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
    turns = [
        {"role": t.role, "content": t.content, "timestamp": t.timestamp, "source": t.source}
        for t in history
    ]
    if session.agent == "aetheria":
        from soveryn.app.heartbeat_in_messages import fold_heartbeat_notes

        turns = fold_heartbeat_notes(conv, session, turns)
    return jsonify({
        "session_id": session_id,
        "agent": session.agent,
        "turns": turns,
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
    if not isinstance(message, str):
        return _err("invalid_message", "message must be a string", 400)

    images, pdfs, attach_err = _validate_attachments(body.get("attachments"), agent)
    if attach_err is not None:
        return attach_err

    if not message.strip() and not images and not pdfs:
        return _err("invalid_message", "message must be a non-empty string", 400)

    # PDF intake: splice extracted text into the turn before the loop.
    # Images still go through AgentLoop vision splice unchanged.
    if pdfs:
        message = _splice_pdf_attachments(message.strip() or "(pdf)", pdfs)
    elif not message.strip():
        message = "(image)"

    source, source_err = _validate_source(body.get("source"))
    if source_err is not None:
        return source_err

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
    from soveryn.rooms import context as room_ctx

    env = state.get("env")
    root = str(getattr(env, "data_root", "")) if env is not None else ""
    tok_dm = room_ctx.dm_session_id.set(session_id if agent == "aetheria" else None)
    tok_root = room_ctx.data_root.set(root or None)
    # Room sessions use title [room:…] — mark room context for projection.
    room_sid = None
    try:
        meta = state["conv_store"].get_session(session_id)
        if meta and meta.title and str(meta.title).startswith("[room:"):
            room_sid = session_id
    except Exception:
        pass
    tok_room = room_ctx.room_session_id.set(room_sid)
    try:
        response = loop.process_message(
            session_id, message, attachments=images, source=source,
        )
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
    finally:
        room_ctx.dm_session_id.reset(tok_dm)
        room_ctx.data_root.reset(tok_root)
        room_ctx.room_session_id.reset(tok_room)

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
    if isinstance(event, ApprovalPendingEvent):
        return {
            "type": "approval_pending",
            "approval_id": event.approval_id,
            "citizen": event.citizen,
            "tool": event.tool,
            "args": event.args,
            "call_id": event.call_id,
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
    if not isinstance(message, str):
        return _err("invalid_message", "message must be a string", 400)

    images, pdfs, attach_err = _validate_attachments(body.get("attachments"), agent)
    if attach_err is not None:
        return attach_err

    if not message.strip() and not images and not pdfs:
        return _err("invalid_message", "message must be a non-empty string", 400)

    if pdfs:
        message = _splice_pdf_attachments(message.strip() or "(pdf)", pdfs)
    elif not message.strip():
        message = "(image)"

    source, source_err = _validate_source(body.get("source"))
    if source_err is not None:
        return source_err

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
            # Terminate the stream with a DoneEvent-shaped frame — the resolver
            # short-circuits the normal turn, so without this the UI never gets
            # the "done" it waits for and the thinking spinner hangs forever.
            # Surface the resolution note (e.g. "[posted to X: <url>]") as content.
            yield _sse({
                "type": "done",
                "content": x_result.note,
                "finish_reason": "stop",
                "tool_calls": None,
                "usage": None,
                "context_usage": None,
            })

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

    from soveryn.app.deferred_chat import ACK, try_defer_chat

    deferred_id = try_defer_chat(
        agent=agent, session_id=session_id, message=message, state=state,
    )
    if deferred_id:
        def _generate_deferred():
            yield _sse({"type": "token", "delta": ACK})
            yield _sse({
                "type": "done",
                "content": ACK,
                "finish_reason": "stop",
                "deferred": True,
                "commission_id": deferred_id,
                "tool_calls": None,
                "usage": None,
                "context_usage": None,
            })

        return Response(
            stream_with_context(_generate_deferred()),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Content-Type": "text/event-stream; charset=utf-8",
            },
        )

    from soveryn.rooms import context as room_ctx

    env = state.get("env")
    root = str(getattr(env, "data_root", "")) if env is not None else ""
    tok_dm = room_ctx.dm_session_id.set(session_id if agent == "aetheria" else None)
    tok_root = room_ctx.data_root.set(root or None)
    room_sid = None
    try:
        meta = state["conv_store"].get_session(session_id)
        if meta and meta.title and str(meta.title).startswith("[room:"):
            room_sid = session_id
    except Exception:
        pass
    tok_room = room_ctx.room_session_id.set(room_sid)

    # ── Open the AgentLoop stream and pump the first chunk *before* returning
    # the SSE Response. This lets setup errors (session mismatch, recall
    # failure, upstream HTTP error before any chunk) translate to JSON 4xx/5xx
    # per constraint 3, rather than appearing inside a half-opened text/event-stream.
    try:
        event_iter = loop.process_message_stream(
            session_id, message, attachments=images, source=source,
        )
        # Pre-fetch the first event so setup errors surface here.
        try:
            first_event = next(event_iter)
        except StopIteration:
            # Generator returned without yielding anything (shouldn't happen on
            # success; AgentLoop always yields at least a DoneEvent or ErrorEvent).
            room_ctx.dm_session_id.reset(tok_dm)
            room_ctx.data_root.reset(tok_root)
            room_ctx.room_session_id.reset(tok_room)
            return _err("internal_error", "AgentLoop yielded no events", 500)
    except AgentLoopError as e:
        room_ctx.dm_session_id.reset(tok_dm)
        room_ctx.data_root.reset(tok_root)
        room_ctx.room_session_id.reset(tok_room)
        msg = str(e)
        if "does not exist" in msg:
            return _err("missing_session", msg, 404)
        if "belongs to agent" in msg:
            return _err("session_agent_mismatch", msg, 409)
        return _err("internal_error", msg, 500)
    except LlamaServerTimeout as e:
        room_ctx.dm_session_id.reset(tok_dm)
        room_ctx.data_root.reset(tok_root)
        room_ctx.room_session_id.reset(tok_room)
        return _err("chat_timeout", str(e), 504)
    except LlamaServerError as e:
        room_ctx.dm_session_id.reset(tok_dm)
        room_ctx.data_root.reset(tok_root)
        room_ctx.room_session_id.reset(tok_room)
        return _err("chat_server_error", str(e), 502)
    except RoutingError as e:
        room_ctx.dm_session_id.reset(tok_dm)
        room_ctx.data_root.reset(tok_root)
        room_ctx.room_session_id.reset(tok_room)
        return _err("unknown_agent", str(e), 400)
    except Exception as e:
        room_ctx.dm_session_id.reset(tok_dm)
        room_ctx.data_root.reset(tok_root)
        room_ctx.room_session_id.reset(tok_room)
        return _err("chat_server_error", f"{type(e).__name__}: {e}", 502)

    # ── Setup OK. Now wrap the iterator in an SSE response.
    def _generate():
        try:
            # First event was already pulled — emit it (skip if voice-only).
            first_payload = _event_to_dict(first_event)
            if first_payload is not None:
                yield _sse(first_payload)
            for event in event_iter:
                payload = _event_to_dict(event)
                if payload is not None:
                    yield _sse(payload)
        finally:
            room_ctx.dm_session_id.reset(tok_dm)
            room_ctx.data_root.reset(tok_root)
            room_ctx.room_session_id.reset(tok_room)

    return Response(
        stream_with_context(_generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Content-Type": "text/event-stream; charset=utf-8",
        },
    )
