"""Flask blueprint for SOVERYN Messenger routes.

All routes mounted under /m/*. Auth-gated except /m/pair and /m/pair/<code>;
admin routes (/m/pair, /m/devices) refuse non-localhost requests.
"""
from __future__ import annotations
import json
from functools import wraps
from pathlib import Path as _P

from flask import (
    Blueprint, Response, request, jsonify, render_template_string,
    send_from_directory,
)

from soveryn.agents.loop import (
    DoneEvent, ErrorEvent, TokenEvent, ToolCallEvent, ToolResultEvent,
)
from soveryn.app.messenger.store import MessengerStore
from soveryn.app.messenger.pairing import (
    mint_pairing_token, claim_pairing_token, PairingError,
)
from soveryn.app.messenger.auth import (
    verify_device_secret, AuthError,
)
from soveryn.app.messenger.threads import (
    create_thread, get_thread, list_threads, set_thread_muted,
    touch_thread, ThreadError,
)
from soveryn.memory.conversation_store import ConversationStore


_LOCALHOST_ADDRS = {"127.0.0.1", "::1"}


def _is_localhost() -> bool:
    return request.remote_addr in _LOCALHOST_ADDRS


def _require_localhost(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not _is_localhost():
            return jsonify({"error": "admin routes require localhost"}), 403
        return fn(*args, **kwargs)
    return wrapper


def _require_auth(messenger_store: MessengerStore):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            header = request.headers.get("Authorization", "")
            if not header.startswith("Bearer "):
                return jsonify({"error": "missing bearer token"}), 401
            secret = header[len("Bearer "):]
            try:
                device = verify_device_secret(messenger_store, secret=secret)
            except AuthError as e:
                return jsonify({"error": str(e)}), 401
            request.authed_device = device
            return fn(*args, **kwargs)
        return wrapper
    return deco


_PAIRING_HTML = """
<!doctype html><html><body>
<h1>SOVERYN — pair a new device</h1>
<form method="post" action="/m/pair">
  <label>Label <input name="label" value="phone"></label>
  <button type="submit">Mint pairing code</button>
</form>
{% if code %}
<h2>Code: {{ code }}</h2>
<p>Enter this on the phone within 5 minutes.</p>
{% endif %}
</body></html>
"""


def build_messenger_blueprint(
    *,
    messenger_store: MessengerStore,
    conv_store: ConversationStore,
    agent_loops: dict,  # name → AgentLoop; used in Task 9
) -> Blueprint:
    bp = Blueprint("messenger", __name__, url_prefix="/m")
    auth_required = _require_auth(messenger_store)

    @bp.route("/pair", methods=["GET", "POST"])
    @_require_localhost
    def pair():
        code = None
        if request.method == "POST":
            body = request.get_json(silent=True) or {}
            label = body.get("label") or request.form.get("label") or "device"
            token = mint_pairing_token(messenger_store, label=label)
            code = token.code
            if request.is_json:
                return jsonify({"code": code, "expires_at": token.expires_at})
        return render_template_string(_PAIRING_HTML, code=code)

    @bp.route("/pair/<code>", methods=["POST"])
    def pair_claim(code: str):
        body = request.get_json(silent=True) or {}
        device_label = body.get("device_label", "unknown device")
        try:
            device = claim_pairing_token(
                messenger_store, code=code, device_label=device_label,
            )
        except PairingError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({
            "device_id": device.device_id,
            "secret": device.secret,
            "label": device.label,
        })

    @bp.route("/threads", methods=["GET"])
    @auth_required
    def threads_list():
        out = list_threads(messenger_store, user_id="jon")
        return jsonify({
            "threads": [
                {
                    "thread_id": t.thread_id,
                    "agent": t.agent,
                    "title": t.title,
                    "last_activity": t.last_activity,
                    "muted": t.muted,
                }
                for t in out
            ],
        })

    @bp.route("/threads", methods=["POST"])
    @auth_required
    def threads_create():
        body = request.get_json(silent=True) or {}
        agent = body.get("agent", "")
        title = body.get("title")
        try:
            thread = create_thread(
                messenger_store, conv_store,
                user_id="jon", agent=agent, title=title,
            )
        except ThreadError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({
            "thread_id": thread.thread_id,
            "agent": thread.agent,
            "title": thread.title,
        })

    @bp.route("/threads/<thread_id>/send_stream", methods=["POST"])
    @auth_required
    def send_stream(thread_id: str):
        body = request.get_json(silent=True) or {}
        client_msg_id = body.get("client_msg_id")
        content = body.get("content", "")
        agent_in_body = body.get("agent", "")
        if not client_msg_id or not content:
            return jsonify({"error": "client_msg_id + content required"}), 400

        thread = get_thread(messenger_store, thread_id=thread_id)
        if thread is None:
            return jsonify({"error": "unknown thread"}), 404
        if thread.agent != agent_in_body:
            return jsonify({
                "error": (
                    f"thread bound to {thread.agent}; client sent {agent_in_body}"
                )
            }), 400

        # Idempotency check
        cached = messenger_store.idempotency_lookup_or_record(
            client_msg_id=client_msg_id,
            thread_id=thread_id,
            device_id=request.authed_device.device_id,
        )
        if cached is not None and cached:
            return jsonify(cached)

        loop = agent_loops.get(thread.agent)
        if loop is None:
            return jsonify({
                "error": f"agent_loop for {thread.agent} not loaded"
            }), 503

        def _stream():
            collected = []
            for event in loop.process_message_stream(thread.session_id, content):
                if isinstance(event, TokenEvent):
                    payload = {"type": "token", "delta": event.delta}
                elif isinstance(event, ToolCallEvent):
                    payload = {"type": "tool_call",
                               "call_id": event.call_id,
                               "name": event.name,
                               "args": event.args}
                elif isinstance(event, ToolResultEvent):
                    payload = {"type": "tool_result",
                               "call_id": event.call_id,
                               "name": event.name,
                               "content": event.content}
                elif isinstance(event, DoneEvent):
                    payload = {
                        "type": "done",
                        "content": event.content,
                        "finish_reason": event.finish_reason,
                    }
                    collected.append(event)
                elif isinstance(event, ErrorEvent):
                    payload = {"type": "error",
                               "code": event.code,
                               "message": event.message}
                else:
                    continue
                # NOTE: use json.dumps, not flask.jsonify — by the time this
                # generator yields, the request context has been torn down,
                # and jsonify raises "Working outside of application context".
                yield f"data: {json.dumps(payload)}\n\n"
            if collected:
                # Cache the final DoneEvent for idempotent retries.
                final = {
                    "content": collected[-1].content,
                    "finish_reason": collected[-1].finish_reason,
                }
                messenger_store.idempotency_set_response(
                    client_msg_id=client_msg_id, response=final,
                )
            touch_thread(messenger_store, thread_id=thread_id)

        return Response(_stream(), mimetype="text/event-stream")

    # PWA static assets — registered LAST so the catch-all `<path:path>` only
    # picks up requests that didn't match a more-specific route above.
    # Werkzeug orders rules by specificity at match time, so this is belt-and-
    # braces, not strictly required for correctness.
    _PWA_DIR = _P(__file__).resolve().parent.parent.parent / "platform" / "web" / "pwa"

    @bp.route("/pwa/<path:path>", methods=["GET"])
    def pwa_static(path: str):
        return send_from_directory(str(_PWA_DIR), path)

    @bp.route("/", methods=["GET"])
    @bp.route("/<path:path>", methods=["GET"])
    def pwa_assets(path: str = ""):
        if not path or path.endswith("/"):
            path = "index.html"
        return send_from_directory(str(_PWA_DIR), path)

    return bp
