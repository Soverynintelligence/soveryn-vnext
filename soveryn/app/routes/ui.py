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
from urllib.parse import urlencode

from flask import Blueprint, jsonify, make_response, redirect, request

bp = Blueprint("ui", __name__)

COMMAND_CENTER_TEMPLATE = Path(__file__).parent.parent / "templates" / "command_center.html"
CITIZENS_TEMPLATE = Path(__file__).parent.parent / "templates" / "citizens.html"
FLEET_TEMPLATE = Path(__file__).parent.parent / "templates" / "fleet.html"
CHARTERS_TEMPLATE = Path(__file__).parent.parent / "templates" / "charters.html"
LOUNGE_TEMPLATE = Path(__file__).parent.parent / "templates" / "lounge.html"
CATHEDRAL_TEMPLATE = Path(__file__).parent.parent / "templates" / "cathedral.html"
HOUSE_TEMPLATE = Path(__file__).parent.parent / "templates" / "house.html"
ESTATE_TEMPLATE = Path(__file__).parent.parent / "templates" / "estate.html"

# ── Shared nav (cc full revamp, swap 1) ──────────────────────────────────────
# Every Desk-style page puts ``<!--sd-nav:KEY-->`` inside its .plate; the
# server swaps in one nav so all pages show the same five doors.
SD_NAV_ITEMS = (
    ("desk", "/command-center", "Desk"),
    ("messages", "/messages", "Messages"),
    ("staff", "/citizens", "Staff"),
    ("estate", "/estate", "Estate"),
    ("library", "/documents", "Library"),
)
_SD_NAV_MARK = re.compile(r"<!--sd-nav:([a-z]+)-->")
_SD_NAV_CSS = (
    "<style id=\"sd-nav-css\">"
    ".plate nav.sd-nav{display:flex;gap:4px;margin-left:12px;flex-wrap:nowrap;align-items:center;flex:0 0 auto}"
    "@media (max-width:760px){.plate nav.sd-nav{flex-wrap:wrap;flex:1 1 100%;margin-left:0}}"
    ".plate nav.sd-nav a{display:inline-block;padding:6px 11px;border-radius:6px;text-decoration:none;"
    "color:rgba(232,227,213,.55);font:13px/1.2 system-ui,-apple-system,Segoe UI,sans-serif;"
    "letter-spacing:normal;text-transform:none;border:0;background:none}"
    ".plate nav.sd-nav a.active,.plate nav.sd-nav a:hover{background:rgba(192,130,79,.14);color:#ece6d6}"
    ".plate nav.sd-nav .sd-sep{width:1px;height:16px;background:rgba(232,227,213,.15);margin:0 6px}"
    ".plate nav.sd-nav a.sd-archive{font-size:12px;opacity:.75}"
    "</style>"
)


def sd_nav_html(active: str) -> str:
    links = []
    for key, href, label in SD_NAV_ITEMS:
        cur = ' class="active keep" aria-current="page"' if key == active else ' class="keep"'
        links.append(f'<a href="{href}"{cur}>{label}</a>')
    house = ' class="sd-archive active keep" aria-current="page"' if active == "house" else ' class="sd-archive keep"'
    links.append('<span class="sd-sep" aria-hidden="true"></span>')
    links.append(f'<a href="/house"{house} title="Older panels, being folded into Estate and Library">House</a>')
    return (_SD_NAV_CSS + '<nav class="sd-nav" data-testid="sd-nav" aria-label="SOVERYN">'
            + "".join(links) + "</nav>")


def apply_sd_nav(html: str) -> str:
    """Swap every ``<!--sd-nav:KEY-->`` marker for the shared nav (function repl: no backrefs)."""
    return _SD_NAV_MARK.sub(lambda m: sd_nav_html(m.group(1)), html)

# Phone / handheld — not tablets (iPad) so desk-sized glass still gets CC.
_PHONE_UA_RE = re.compile(
    r"(?:iPhone|iPod|Android.*Mobile|Windows Phone|BlackBerry|webOS|"
    r"Mobile(?:\s|;|/)|Opera Mini|IEMobile)",
    re.IGNORECASE,
)


# Phone Home Screen PWA caches /messages by URL. Bump this when the list chrome
# or thread JS changes so iOS is forced onto a new document (start_url + 302).
_MESSAGES_BUILD = "20261105sky"
_CITIZEN_ICONS_CSS = Path(__file__).resolve().parents[2] / "static" / "citizen-icons.css"
_CITIZEN_ICONS_JS = Path(__file__).resolve().parents[2] / "static" / "citizen-icons.js"


def _inline_citizen_icons(html: str) -> str:
    """Bake faces into Messages HTML. Phone PWAs often fail /static/ (gate or cache)
    and then fall back to letter circles."""
    css = (
        _CITIZEN_ICONS_CSS.read_text(encoding="utf-8")
        if _CITIZEN_ICONS_CSS.is_file() else ""
    )
    js = (
        _CITIZEN_ICONS_JS.read_text(encoding="utf-8")
        if _CITIZEN_ICONS_JS.is_file() else ""
    )
    # Do not use re.sub with the file body as the replacement string.
    # citizen-icons.js contains `\w` / `\b`; Python treats those as backrefs
    # and 500s Messages. Literal replace only.
    html = _replace_once(
        html,
        r'<link rel="stylesheet" href="/static/citizen-icons.css?v=',
        '">',
        "<style id=\"citizen-icons\">\n" + css + "\n</style>",
    )
    html = _replace_once(
        html,
        r'<script src="/static/citizen-icons.js?v=',
        '"></script>',
        "<script>\n" + js + "\n</script>",
    )
    return html


_DESK_CSS = Path(__file__).resolve().parents[2] / "static" / "desk.css"


def _inline_desk_css(html: str) -> str:
    """Bake the shared Desk house style into the phone pages (same reason as the
    citizen icons: PWAs on the phone can fail /static/). Literal replace only."""
    if not _DESK_CSS.is_file():
        return html
    return _replace_once(
        html,
        '<link rel="stylesheet" href="/static/desk.css?v=',
        '">',
        "<style id=\"desk-css\">\n" + _DESK_CSS.read_text(encoding="utf-8") + "\n</style>",
    )


_MESSAGES_SIDEBAR = Path(__file__).parent.parent / "templates" / "_messages_sidebar.html"


def _inline_messages_sidebar(html: str) -> str:
    """Bake the Messages sidebar (list + status dots) into both Messages pages."""
    part = _MESSAGES_SIDEBAR.read_text(encoding="utf-8") if _MESSAGES_SIDEBAR.is_file() else ""
    return html.replace("<!--mx-sidebar-->", part, 1)


def _replace_once(html: str, prefix: str, suffix: str, block: str) -> str:
    start = html.find(prefix)
    if start < 0:
        return html
    end = html.find(suffix, start)
    if end < 0:
        return html
    return html[:start] + block + html[end + len(suffix):]


def _serve_html(path: Path, *, missing_label: str):
    if not path.is_file():
        return jsonify({"error": {
            "code": "ui_unavailable",
            "message": f"{missing_label} template missing at {path}",
        }}), 500
    html = path.read_text(encoding="utf-8")
    if "<!--mx-sidebar-->" in html:
        html = _inline_messages_sidebar(html)
    if "<!--sd-nav:" in html:
        html = apply_sd_nav(html)
    if path.name in ("messages.html", "message_thread.html"):
        html = _inline_citizen_icons(html)
    if path.name in ("messages.html", "message_thread.html", "room.html"):
        html = _inline_desk_css(html)
    resp = make_response(html, 200)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    resp.headers["X-SOVERYN-UI-Source"] = "vnext-native"
    # Phone Safari / home-screen bookmarks love stale HTML; Messages must be fresh.
    if path.name in (
        "messages.html", "message_thread.html", "room.html", "command_center.html",
        "citizens.html", "documents.html", "lounge.html", "house.html", "estate.html",
    ):
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


@bp.get("/house")
def house():
    """Everything the Desk no longer shows: ops, memory, boards, lounge, pulse."""
    return _serve_html(HOUSE_TEMPLATE, missing_label="House")


@bp.get("/citizens")
def citizens_board():
    """Serve the Citizens board (Phase 3 console)."""
    return _serve_html(CITIZENS_TEMPLATE, missing_label="Citizens board")


@bp.get("/estate")
def estate_page():
    """Estate — rig, Sparks, daemons, Ares, public agents, automations, gate (was Fleet + House ops)."""
    return _serve_html(ESTATE_TEMPLATE, missing_label="Estate")


@bp.get("/fleet")
def fleet_page():
    """Fleet merged into Estate (cc full revamp, swap 1). Old bookmarks keep working."""
    qs = request.query_string.decode("utf-8", "ignore")
    return redirect("/estate" + (f"?{qs}" if qs else ""), code=302)


@bp.get("/charters")
def charters_board():
    """Imported botdirectory job charters — review only, never live."""
    return _serve_html(CHARTERS_TEMPLATE, missing_label="Charters board")


@bp.get("/lounge")
def lounge_page():
    """The Lounge — the team's room with no agenda. Jon participates directly."""
    return _serve_html(LOUNGE_TEMPLATE, missing_label="Lounge")


@bp.get("/cathedral")
def cathedral_page():
    """The Cathedral — the house's memory as a galaxy. Live from the lattice."""
    return _serve_html(CATHEDRAL_TEMPLATE, missing_label="Cathedral")


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


def _messages_build_redirect():
    """Force iOS Home Screen off a frozen /messages URL onto a new query."""
    if request.args.get("b") == _MESSAGES_BUILD:
        return None
    args = request.args.to_dict(flat=True)
    args["b"] = _MESSAGES_BUILD
    qs = urlencode(args)
    dest = f"/messages?{qs}" if qs else f"/messages?b={_MESSAGES_BUILD}"
    resp = redirect(dest, code=302)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp


@bp.get("/messages")
def messages_page():
    """Messenger-style contacts list — tap a citizen to open their 1:1."""
    bounced = _messages_build_redirect()
    if bounced is not None:
        return bounced
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


_MESSAGE_AGENT_ALIAS = {"kernel": "forge"}


def _messages_agent(agent: str) -> str:
    """Old Kernel-citizen links open Forge. Kernel the build brain stays at /build."""
    key = (agent or "").strip().lower()
    return _MESSAGE_AGENT_ALIAS.get(key, key)


def _thread_build_redirect(agent: str):
    """Same iOS cache-bust as the contacts list — /messages/<agent> is its own URL."""
    if request.args.get("b") == _MESSAGES_BUILD:
        return None
    args = request.args.to_dict(flat=True)
    args["b"] = _MESSAGES_BUILD
    qs = urlencode(args)
    dest = f"/messages/{agent}?{qs}" if qs else f"/messages/{agent}?b={_MESSAGES_BUILD}"
    resp = redirect(dest, code=302)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp


@bp.get("/messages/<agent>")
def message_thread_page(agent: str):
    """iMessage-style 1:1 thread — matches /messages list chrome."""
    raw = (agent or "").strip().lower()
    agent = _messages_agent(raw)
    if agent != raw:
        args = request.args.to_dict(flat=True)
        args["b"] = _MESSAGES_BUILD
        resp = redirect(f"/messages/{agent}?{urlencode(args)}", code=302)
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return resp
    bounced = _thread_build_redirect(agent)
    if bounced is not None:
        return bounced
    return _serve_html(MESSAGE_THREAD_TEMPLATE, missing_label="Message thread")


@bp.get("/chat")
def chat_index():
    """Legacy lab chat → Messages (house front door)."""
    agent = _messages_agent(request.args.get("agent") or "")
    if agent:
        return redirect(f"/messages/{agent}", code=302)
    return redirect("/messages", code=302)


@bp.get("/chat/<session_id>")
def chat_session(session_id: str):  # noqa: ARG001 - client may use ?agent=
    """Legacy session URL → Messages (session resume happens in-thread)."""
    agent = _messages_agent(request.args.get("agent") or "")
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
