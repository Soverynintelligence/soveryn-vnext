"""SOVERYN vNext — native UI routes.

Messages is the house front door (all devices). ``/`` redirects to
``/messages``. Command Center at ``/command-center`` is the desk HUD
(ops/tower) — open with ``?desk=1`` from phone if needed.

All templates live in soveryn/app/templates/ — self-contained HTML+CSS+JS,
no framework, no static asset dependencies, reading from the existing vNext
REST API (/api/models, /sessions, /chat_stream, etc.).

The legacy template bridge that previously sat at / moved to /legacy.
"""

from __future__ import annotations

import re
from pathlib import Path

from flask import Blueprint, jsonify, make_response, redirect, request

bp = Blueprint("ui", __name__)

COMMAND_CENTER_TEMPLATE = Path(__file__).parent.parent / "templates" / "command_center.html"
CITIZENS_TEMPLATE = Path(__file__).parent.parent / "templates" / "citizens.html"
FLEET_TEMPLATE = Path(__file__).parent.parent / "templates" / "fleet.html"
CHARTERS_TEMPLATE = Path(__file__).parent.parent / "templates" / "charters.html"

# Phone / handheld — not tablets (iPad) so desk-sized glass still gets CC.
_PHONE_UA_RE = re.compile(
    r"(?:iPhone|iPod|Android.*Mobile|Windows Phone|BlackBerry|webOS|"
    r"Mobile(?:\s|;|/)|Opera Mini|IEMobile)",
    re.IGNORECASE,
)


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
    # Phone Safari / home-screen bookmarks love stale HTML; Messages must be fresh.
    if path.name in ("messages.html", "message_thread.html", "room.html"):
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
    return resp


def _serve_command_center():
    return _serve_html(COMMAND_CENTER_TEMPLATE, missing_label="Command center")


def _is_phone_user_agent(ua: str | None) -> bool:
    return bool(_PHONE_UA_RE.search(ua or ""))


def _force_command_center() -> bool:
    """Explicit overrides so phone can still open the desk HUD."""
    raw = (
        request.args.get("home")
        or request.args.get("desk")
        or ""
    ).strip().lower()
    return raw in (
        "cc",
        "desk",
        "command",
        "command-center",
        "1",
        "true",
        "yes",
    )


def _force_messages() -> bool:
    raw = (request.args.get("home") or "").strip().lower()
    return raw in ("messages", "phone", "m")


@bp.get("/")
def home():
    """House front door → Messages. Desk HUD only when explicitly forced."""
    if _force_command_center():
        return _serve_command_center()
    return redirect("/messages", code=302)


@bp.get("/command-center")
def command_center():
    """Desk HUD. Phone → Messages unless ?desk=1 (or home=cc) is explicit."""
    if (
        _is_phone_user_agent(request.headers.get("User-Agent"))
        and not _force_command_center()
    ):
        return redirect("/messages", code=302)
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


def _messages_static_file(name: str, *, mimetype: str):
    from flask import Response

    path = Path(__file__).resolve().parents[2] / "static" / "messages" / name
    if not path.is_file():
        return jsonify({"error": {
            "code": "ui_unavailable",
            "message": f"messages asset missing at {path}",
        }}), 500
    resp = Response(path.read_text(encoding="utf-8"), mimetype=mimetype)
    # Phones (esp. Home Screen PWAs) love stale JS — never cache these.
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


@bp.get("/messages-sw.js")
def messages_service_worker():
    """Service worker at origin scope so Web Push covers /messages/*."""
    resp = _messages_static_file(
        "sw.js", mimetype="application/javascript; charset=utf-8"
    )
    if isinstance(resp, tuple):
        return resp
    resp.headers["Service-Worker-Allowed"] = "/"
    return resp


@bp.get("/messages-push-client.js")
def messages_push_client():
    """Cache-busted push client — prefer this URL from Messages templates."""
    return _messages_static_file(
        "push-client.js", mimetype="application/javascript; charset=utf-8"
    )


@bp.get("/messages/<agent>")
def message_thread_page(agent: str):
    """iMessage-style 1:1 thread — matches /messages list chrome."""
    return _serve_html(MESSAGE_THREAD_TEMPLATE, missing_label="Message thread")


@bp.get("/chat")
def chat_index():
    """Legacy lab chat → Messages (house front door)."""
    agent = (request.args.get("agent") or "").strip().lower()
    if agent:
        return redirect(f"/messages/{agent}", code=302)
    return redirect("/messages", code=302)


@bp.get("/chat/<session_id>")
def chat_session(session_id: str):  # noqa: ARG001 - client may use ?agent=
    """Legacy session URL → Messages (session resume happens in-thread)."""
    agent = (request.args.get("agent") or "").strip().lower()
    if agent:
        return redirect(
            f"/messages/{agent}?session={session_id}", code=302
        )
    return redirect("/messages", code=302)


BUILD_TEMPLATE = Path(__file__).parent.parent / "templates" / "build_chat.html"


@bp.get("/build")
def build_chat():
    """Kernel — house build brain chat (no agent tools)."""
    return _serve_html(BUILD_TEMPLATE, missing_label="Kernel build chat")
