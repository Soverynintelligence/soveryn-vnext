"""SOVERYN vNext — native UI routes.

Serves the vNext command center at / and the chat page at /chat
(plus /chat/<session_id>). All templates live in
soveryn/app/templates/ — self-contained HTML+CSS+JS, no framework,
no static asset dependencies, reading from the existing vNext REST
API (/api/models, /sessions, /chat, /chat_stream, etc.).

The legacy template bridge that previously sat at / moved to /legacy.
"""

from __future__ import annotations
from pathlib import Path

from flask import Blueprint, jsonify, make_response

bp = Blueprint("ui", __name__)

COMMAND_CENTER_TEMPLATE = Path(__file__).parent.parent / "templates" / "command_center.html"
CITIZENS_TEMPLATE = Path(__file__).parent.parent / "templates" / "citizens.html"
FLEET_TEMPLATE = Path(__file__).parent.parent / "templates" / "fleet.html"
CHARTERS_TEMPLATE = Path(__file__).parent.parent / "templates" / "charters.html"


def _serve_html(path: Path, *, missing_label: str):
    if not path.is_file():
        return jsonify({"error": {
            "code": "ui_unavailable",
            "message": f"{missing_label} template missing at {path}",
        }}), 500
    html = path.read_text(encoding="utf-8")
    resp = make_response(html, 200)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    resp.headers["X-SOVERYN-UI-Source"] = "vnext-native"
    return resp


def _serve_command_center():
    return _serve_html(COMMAND_CENTER_TEMPLATE, missing_label="Command center")


@bp.get("/")
def command_center():
    """Serve the vNext command center."""
    return _serve_command_center()


@bp.get("/citizens")
def citizens_board():
    """Serve the Citizens board (Phase 3 console)."""
    return _serve_html(CITIZENS_TEMPLATE, missing_label="Citizens board")


@bp.get("/fleet")
def fleet_page():
    """Fleet — Rig headroom, session traffic, house counts (not on Command home)."""
    return _serve_html(FLEET_TEMPLATE, missing_label="Fleet")


@bp.get("/charters")
def charters_board():
    """Imported botdirectory job charters — review only, never live."""
    return _serve_html(CHARTERS_TEMPLATE, missing_label="Charters board")


CHAT_TEMPLATE = Path(__file__).parent.parent / "templates" / "chat.html"
ROOM_TEMPLATE = Path(__file__).parent.parent / "templates" / "room.html"
MESSAGES_TEMPLATE = Path(__file__).parent.parent / "templates" / "messages.html"
MESSAGE_THREAD_TEMPLATE = Path(__file__).parent.parent / "templates" / "message_thread.html"


def _serve_chat_html():
    if not CHAT_TEMPLATE.is_file():
        return jsonify({"error": {
            "code": "ui_unavailable",
            "message": f"Chat template missing at {CHAT_TEMPLATE}",
        }}), 500
    html = CHAT_TEMPLATE.read_text(encoding="utf-8")
    resp = make_response(html, 200)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    resp.headers["X-SOVERYN-UI-Source"] = "vnext-native"
    return resp


@bp.get("/room")
def room_page():
    """Group collaboration room — CoS + one peer + Jon."""
    return _serve_html(ROOM_TEMPLATE, missing_label="Room")


@bp.get("/messages")
def messages_page():
    """Messenger-style contacts list — tap a citizen to open their 1:1."""
    return _serve_html(MESSAGES_TEMPLATE, missing_label="Messages")


@bp.get("/messages/<agent>")
def message_thread_page(agent: str):
    """iMessage-style 1:1 thread — matches /messages list chrome."""
    return _serve_html(MESSAGE_THREAD_TEMPLATE, missing_label="Message thread")


@bp.get("/chat")
def chat_index():
    """Serve the chat page (agent picker via ?agent=X query string, client-side)."""
    return _serve_chat_html()


@bp.get("/chat/<session_id>")
def chat_session(session_id: str):  # noqa: ARG001 - client reads session from URL
    """Serve the chat page; the client JS reads the session_id from the URL."""
    return _serve_chat_html()


BUILD_TEMPLATE = Path(__file__).parent.parent / "templates" / "build_chat.html"


@bp.get("/build")
def build_chat():
    """Kernel — house build brain chat (no agent tools)."""
    return _serve_html(BUILD_TEMPLATE, missing_label="Kernel build chat")
