"""Room sidecars + ask_peer (house_post / commission) for group chat v0."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from soveryn.memory.conversation_store import ConversationStore

# Pickable peers (not CoS). Default vett.
PEERS: frozenset[str] = frozenset({"vett", "eve", "kernel", "scotty"})
DEFAULT_PEER = "vett"
COS_ID = "aetheria"

# Marker embedded in 1:1 system turns so chat.html can render a chip.
MESSAGED_MARKER = "⟦room:messaged:{peer}⟧"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def rooms_root(data_root: Path | str) -> Path:
    root = Path(data_root) / "rooms"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _sidecar_path(data_root: Path | str, session_id: str) -> Path:
    return rooms_root(data_root) / f"{session_id}.json"


def _title_for(peer: str) -> str:
    return f"[room:aetheria+{peer}]"


def open_room(
    conv: ConversationStore,
    *,
    data_root: Path | str,
    peer: str = DEFAULT_PEER,
    dm_session_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Create or load a room session (agent=aetheria) + sidecar."""
    peer = (peer or DEFAULT_PEER).strip().lower()
    if peer not in PEERS:
        raise ValueError(f"peer must be one of {sorted(PEERS)}, got {peer!r}")

    if session_id:
        meta = conv.get_session(session_id)
        if meta is None:
            raise ValueError(f"session {session_id!r} not found")
        if meta.agent != COS_ID:
            raise ValueError("room sessions must belong to aetheria")
        path = _sidecar_path(data_root, session_id)
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            data = {
                "session_id": session_id,
                "peer": peer,
                "dm_session_id": dm_session_id,
                "created_at": _utc_now(),
                "events": [],
            }
            path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return data

    # Reuse existing open room for this peer+dm if sidecar matches
    root = rooms_root(data_root)
    if dm_session_id:
        for p in root.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if data.get("peer") == peer and data.get("dm_session_id") == dm_session_id:
                sid = data.get("session_id")
                if sid and conv.get_session(sid) is not None:
                    return data

    sid = conv.new_session(COS_ID, title=_title_for(peer))
    data = {
        "session_id": sid,
        "peer": peer,
        "dm_session_id": dm_session_id,
        "created_at": _utc_now(),
        "events": [],
    }
    _sidecar_path(data_root, sid).write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8"
    )
    # Seed room with a system welcome
    conv.save_turn(
        sid,
        COS_ID,
        "system",
        (
            f"Room · You + Aetheria + {peer.title()}. "
            f"You talk to Aetheria here; when she works with {peer.title()}, "
            f"it shows in this thread. Use Ask {peer.title()} to commission them."
        ),
        source="room",
    )
    return data


def load_room(data_root: Path | str, session_id: str) -> dict[str, Any] | None:
    path = _sidecar_path(data_root, session_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _save_room(data_root: Path | str, data: dict[str, Any]) -> None:
    sid = data["session_id"]
    _sidecar_path(data_root, sid).write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8"
    )


def ask_peer(
    conv: ConversationStore,
    *,
    data_root: Path | str,
    citizens_db: Path | str,
    session_id: str,
    brief: str,
    from_id: str = "jon",
) -> dict[str, Any]:
    """Commission peer via CoS routing; project into room + DM."""
    from soveryn.citizens import post as house_post
    from soveryn.citizens.registry import connect

    brief = (brief or "").strip()
    if not brief:
        raise ValueError("brief must be non-empty")

    room = load_room(data_root, session_id)
    if room is None:
        raise ValueError(f"no room sidecar for {session_id!r}")
    peer = room["peer"]
    at = _utc_now()

    # Route as CoS so we don't require a `jon` citizen row (FK). Jon is the
    # human operating the room UI; the commission is still attributed in body.
    with connect(Path(citizens_db)) as conn:
        result = house_post.route_via_cos(
            conn,
            from_id=COS_ID,
            assignee_id=peer,
            body=f"(Jon, via room)\n\n{brief}",
            at=at,
            subject=f"room ask {peer}",
        )

    marker = MESSAGED_MARKER.format(peer=peer)
    room_line = (
        f"{marker} Messaged {peer.title()} — commissioned.\n"
        f"Brief: {brief}\n"
        f"Commission `{result.get('commission_id')}`."
    )
    conv.save_turn(session_id, COS_ID, "system", room_line, source="room")

    dm = room.get("dm_session_id")
    if dm and conv.get_session(dm) is not None:
        dm_line = (
            f"{marker} Messaged {peer.title()}\n"
            f"Open room to follow the collaboration."
        )
        conv.save_turn(dm, COS_ID, "system", dm_line, source="room")

    event = {
        "type": "messaged_peer",
        "peer": peer,
        "at": at,
        "brief": brief,
        "commission_id": result.get("commission_id"),
        "directive_post_id": result.get("directive_post_id"),
        "room_session_id": session_id,
        "dm_session_id": dm,
    }
    room.setdefault("events", []).append(event)
    _save_room(data_root, room)
    return {"ok": True, "room": room, "event": event, "routing": result}


def collabs_for_dm(data_root: Path | str, dm_session_id: str) -> list[dict[str, Any]]:
    """Recent messaged-peer events linked to this 1:1 session (for chips)."""
    out: list[dict[str, Any]] = []
    root = rooms_root(data_root)
    if not root.is_dir():
        return out
    for p in root.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("dm_session_id") != dm_session_id:
            continue
        for ev in data.get("events") or []:
            if ev.get("type") == "messaged_peer":
                out.append({**ev, "room_session_id": data.get("session_id")})
    out.sort(key=lambda e: e.get("at") or "", reverse=True)
    return out[:20]


def peer_commission_status(
    citizens_db: Path | str, commission_id: str
) -> dict[str, Any] | None:
    """Best-effort commission row for room polling."""
    from soveryn.citizens import commissions
    from soveryn.citizens.registry import connect

    if not commission_id:
        return None
    path = Path(citizens_db)
    if not path.exists():
        return None
    try:
        with connect(path) as conn:
            row = commissions.get(conn, commission_id)
            return row
    except (sqlite3.Error, OSError):
        return None
