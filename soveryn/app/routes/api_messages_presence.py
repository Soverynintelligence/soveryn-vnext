"""Messages sidebar presence: live / busy / down per citizen, from real signals.

GET /api/messages/presence (read-only)

* down  — the citizen's model server (runtime AGENT_TO_SERVER → base_url) did
          not answer ``GET /v1/models`` with 200 inside 1.5 s.
* busy  — server up AND the citizen is mid-work right now: a running
          commission or a recent interactive turn (``build_active_now``, the
          same signal as the Desk's active-now strip).
* live  — server up and not busy.

Inbox-only teammates (t_critic / t_scout) have no model seat → ``inbox``.
Probes run concurrently and the whole answer is cached for 10 s so a few open
tabs never multiply load on the model routers.
"""

from __future__ import annotations

import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify

bp = Blueprint("api_messages_presence", __name__)

_CACHE: dict = {"at": 0.0, "body": None}
_LOCK = threading.Lock()
_TTL_S = 10.0
_PROBE_TIMEOUT_S = 1.5
INBOX_ONLY = ("t_critic", "t_scout")


def _probe(url: str) -> tuple[bool, int | None, str]:
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/v1/models", timeout=_PROBE_TIMEOUT_S) as r:
            ok = r.status == 200
            return ok, int((time.monotonic() - t0) * 1000), "" if ok else f"http {r.status}"
    except Exception as exc:  # unreachable, timeout, refused
        return False, None, type(exc).__name__


def _active_citizens() -> set[str]:
    try:
        from soveryn.app.routes.api_citizens import _db_path
        from soveryn.citizens.active_now import build_active_now

        state = current_app.extensions.get("soveryn") or {}
        env = state.get("env")
        conv_db = getattr(env, "conversations_db", None) if env is not None else None
        if conv_db is None:
            cs = state.get("conv_store")
            conv_db = getattr(cs, "db_path", None) if cs is not None else None
        payload = build_active_now(_db_path(), conv_db)
        return {str(a.get("citizen") or a.get("agent") or "") for a in payload.get("active", [])}
    except Exception:
        return set()


def _build() -> dict:
    from soveryn.config.runtime import AGENT_TO_SERVER, MESSAGES_CONTACTS, MODEL_SERVERS

    servers = {s.name: s for s in MODEL_SERVERS}
    seats = {}
    for agent in MESSAGES_CONTACTS:
        srv = servers.get(AGENT_TO_SERVER.get(agent, ""))
        seats[agent] = srv
    with ThreadPoolExecutor(max_workers=max(1, len(seats))) as ex:
        futs = {a: ex.submit(_probe, s.base_url) for a, s in seats.items() if s is not None}
        probes = {a: f.result() for a, f in futs.items()}
    busy = _active_citizens()
    out = []
    for agent, srv in seats.items():
        ok, ms, err = probes.get(agent, (False, None, "no seat"))
        state = "down" if not ok else ("busy" if agent in busy else "live")
        out.append({
            "id": agent,
            "state": state,
            "model_ok": ok,
            "latency_ms": ms,
            "error": err or None,
            "seat": getattr(srv, "name", None),
            "busy": agent in busy,
        })
    for agent in INBOX_ONLY:
        out.append({"id": agent, "state": "inbox", "model_ok": None, "latency_ms": None,
                    "error": None, "seat": None, "busy": False})
    return {"citizens": out, "fetched_at": datetime.now(timezone.utc).isoformat(), "ttl_s": _TTL_S}


@bp.get("/api/messages/presence")
def presence():
    now = time.monotonic()
    with _LOCK:
        if _CACHE["body"] is not None and now - _CACHE["at"] < _TTL_S:
            return jsonify(_CACHE["body"]), 200
    body = _build()
    with _LOCK:
        _CACHE.update(at=time.monotonic(), body=body)
    return jsonify(body), 200


# ── Sidebar summary: last message + unread count per contact ────────────────
# Mirrors isResumableDmSession() in message_thread.html so the sidebar points
# at the same thread the page will open. Server-side so phones never pull a
# 600 KB history just to draw a preview line.
import json as _json
import re as _re

from flask import request

_SKIP_TITLE = _re.compile(r"^\[(heartbeat|direct:|commission|signal|specialist|webhook)", _re.I)


def _is_dm(s) -> bool:
    t = (getattr(s, "title", None) or "").strip()
    if not t:
        return True
    if t.startswith("[room:") or _SKIP_TITLE.match(t):
        return False
    if t.startswith("automation:") or t.startswith("verify-"):
        return False
    if t.startswith("[m]"):
        return True
    return not t.startswith("[")


def _local_naive(ts):
    """Turn timestamps are naive server-local; the browser's 'seen' is ISO with Z.
    Compare both as naive local datetimes. Unparseable → None."""
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.astimezone().replace(tzinfo=None) if d.tzinfo else d


def _preview(text: str, n: int = 140) -> str:
    s = _re.sub(r"\s+", " ", str(text or "")).strip()
    s = _re.sub(r"[*`#>]+", "", s)
    return s if len(s) <= n else s[: n - 1] + "…"


@bp.get("/api/messages/sidebar")
def sidebar():
    from soveryn.config.runtime import MESSAGES_CONTACTS

    try:
        since = _json.loads(request.args.get("since") or "{}")
        if not isinstance(since, dict):
            since = {}
    except ValueError:
        since = {}
    conv = (current_app.extensions.get("soveryn") or {}).get("conv_store")
    out = []
    for agent in tuple(MESSAGES_CONTACTS) + INBOX_ONLY:
        row = {"id": agent, "session_id": None, "title": None, "updated_at": None,
               "last": None, "unread": 0, "inbox": agent in INBOX_ONLY}
        try:
            sessions = conv.list_sessions(agent=agent, limit=30) if conv else []
            s = sessions[0] if (agent in INBOX_ONLY and sessions) else next((x for x in sessions if _is_dm(x)), None)
            if s is not None:
                row.update(session_id=s.session_id, title=s.title, updated_at=s.updated_at)
                hist = conv.load_history(s.session_id)
                visible = [t for t in hist if t.role in ("user", "assistant") and (t.content or "").strip()]
                if visible:
                    last = visible[-1]
                    row["last"] = {"role": last.role, "preview": _preview(last.content), "at": last.timestamp}
                seen = _local_naive(since.get(agent))
                if seen:
                    row["unread"] = sum(1 for t in visible if t.role == "assistant"
                                        and (_local_naive(t.timestamp) or seen) > seen)
                elif visible and visible[-1].role == "assistant":
                    row["unread"] = 1   # never opened on this device: flag the waiting reply
        except Exception as exc:  # one bad contact never blanks the sidebar
            row["error"] = type(exc).__name__
        out.append(row)
    return jsonify({"contacts": out}), 200
