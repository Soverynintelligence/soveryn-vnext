"""Room sidecars + ask_peer (house_post / commission) for group chat v0."""

from __future__ import annotations

import json
import re
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


def _title_for_peers(peers: list[str]) -> str:
    parts = "+".join(p for p in peers if p)
    return f"[room:aetheria+{parts}]" if parts else "[room:aetheria]"


def room_peers(room: dict[str, Any] | None) -> list[str]:
    """Normalize peer list (legacy single `peer` + multi `peers`)."""
    if not room:
        return []
    out: list[str] = []
    for p in room.get("peers") or []:
        pid = str(p).strip().lower()
        if pid in PEERS and pid not in out:
            out.append(pid)
    legacy = (room.get("peer") or "").strip().lower()
    if legacy in PEERS and legacy not in out:
        out.insert(0, legacy)
    return out


def _normalize_room(data: dict[str, Any]) -> dict[str, Any]:
    """Ensure peers[] exists; keep peer= as primary for older clients."""
    peers = room_peers(data)
    if not peers:
        peers = [DEFAULT_PEER]
    data["peers"] = peers
    data["peer"] = peers[0]
    return data


def open_room(
    conv: ConversationStore,
    *,
    data_root: Path | str,
    peer: str = DEFAULT_PEER,
    dm_session_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Create or load a room session (agent=aetheria) + sidecar.

    Multi-peer: if a room already exists for this DM, adding another peer
    (e.g. Eve) joins that same thread so hands share one group.
    """
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
            data = _normalize_room(json.loads(path.read_text(encoding="utf-8")))
            if peer not in room_peers(data):
                data = add_peer_to_room(
                    conv, data_root=data_root, session_id=session_id, peer=peer
                )
            else:
                _save_room(data_root, data)
            return data
        data = _normalize_room({
            "session_id": session_id,
            "peer": peer,
            "peers": [peer],
            "dm_session_id": dm_session_id,
            "created_at": _utc_now(),
            "events": [],
        })
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return data

    # Reuse the DM's existing group room (any peer) so we grow one thread
    # instead of spawning parallel Vett-only / Eve-only rooms.
    root = rooms_root(data_root)
    if dm_session_id:
        for p in root.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if data.get("dm_session_id") != dm_session_id:
                continue
            sid = data.get("session_id")
            if not sid or conv.get_session(sid) is None:
                continue
            data = _normalize_room(data)
            if peer not in room_peers(data):
                return add_peer_to_room(
                    conv, data_root=data_root, session_id=sid, peer=peer
                )
            _save_room(data_root, data)
            return data

    sid = conv.new_session(COS_ID, title=_title_for(peer))
    data = _normalize_room({
        "session_id": sid,
        "peer": peer,
        "peers": [peer],
        "dm_session_id": dm_session_id,
        "created_at": _utc_now(),
        "events": [],
    })
    _sidecar_path(data_root, sid).write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8"
    )
    # No welcome lecture — messenger-forward. First real turns are
    # To/From peer lines (and Jon's messages) when someone is looped in.
    return data


def add_peer_to_room(
    conv: ConversationStore,
    *,
    data_root: Path | str,
    session_id: str,
    peer: str,
) -> dict[str, Any]:
    """Add a peer to an existing group so the thread stays shared."""
    peer = (peer or "").strip().lower()
    if peer not in PEERS:
        raise ValueError(f"peer must be one of {sorted(PEERS)}, got {peer!r}")
    room = load_room(data_root, session_id)
    if room is None:
        raise ValueError(f"no room sidecar for {session_id!r}")
    room = _normalize_room(room)
    peers = room_peers(room)
    if peer in peers:
        return room
    peers.append(peer)
    room["peers"] = peers
    room["peer"] = peers[0]
    # Soft notice in-thread — messenger style, not a lecture
    conv.save_turn(
        session_id,
        COS_ID,
        "system",
        f"Added {peer.title()} to the group.",
        source="room",
    )
    room.setdefault("events", []).append({
        "type": "peer_added",
        "peer": peer,
        "at": _utc_now(),
        "room_session_id": session_id,
        "dm_session_id": room.get("dm_session_id"),
    })
    # Best-effort: retitle session for ops lists
    try:
        conv.update_title(session_id, _title_for_peers(peers))
    except Exception:
        pass
    _save_room(data_root, room)
    return room


def room_transcript_excerpt(
    conv: ConversationStore,
    session_id: str,
    *,
    limit: int = 12,
) -> str:
    """Recent room turns for commission prompts (cross-peer awareness)."""
    try:
        turns = conv.load_history(session_id) or []
    except Exception:
        return ""
    if not turns:
        return ""
    lines: list[str] = []
    for t in turns[-limit:]:
        role = (t.role or "").strip()
        content = (t.content or "").strip()
        if not content:
            continue
        content = re.sub(r"⟦room:(?:messaged|replied):[a-z]+⟧\s*", "", content)
        if role == "user":
            who = "Jon"
        elif content.startswith("[To "):
            who = "Aetheria"
        elif content.startswith("[From "):
            who = content[len("[From ") :].split("]", 1)[0]
            content = content.split("\n", 1)[-1] if "\n" in content else content
        elif role == "system":
            who = "Room"
        else:
            who = "Aetheria"
        excerpt = content if len(content) <= 400 else content[:397] + "…"
        lines.append(f"{who}: {excerpt}")
    return "\n".join(lines)


def load_room(data_root: Path | str, session_id: str) -> dict[str, Any] | None:
    path = _sidecar_path(data_root, session_id)
    if not path.is_file():
        return None
    try:
        return _normalize_room(json.loads(path.read_text(encoding="utf-8")))
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
    peer: str | None = None,
) -> dict[str, Any]:
    """Commission a peer via CoS routing; project into room + DM.

    ``peer`` selects who in a multi-peer room; defaults to primary.
    """
    from soveryn.citizens import post as house_post
    from soveryn.citizens.registry import connect

    brief = (brief or "").strip()
    if not brief:
        raise ValueError("brief must be non-empty")

    room = load_room(data_root, session_id)
    if room is None:
        raise ValueError(f"no room sidecar for {session_id!r}")
    peers = room_peers(room)
    if peer:
        peer = peer.strip().lower()
        if peer not in PEERS:
            raise ValueError(f"peer must be one of {sorted(PEERS)}, got {peer!r}")
        if peer not in peers:
            room = add_peer_to_room(
                conv, data_root=data_root, session_id=session_id, peer=peer
            )
            peers = room_peers(room)
    else:
        peer = peers[0] if peers else room.get("peer") or DEFAULT_PEER
    at = _utc_now()

    # Shared room context so the assignee sees what other hands already did.
    room_ctx = room_transcript_excerpt(conv, session_id, limit=12)
    body = f"(Jon, via room · peers: {', '.join(peers)})\n\n{brief}"
    if room_ctx:
        body = (
            f"{body}\n\n---\n"
            f"Shared group thread (read this — other citizens may already "
            f"have contributed; do not duplicate their work):\n{room_ctx}"
        )

    # Route as CoS so we don't require a `jon` citizen row (FK). Jon is the
    # human operating the room UI; the commission is still attributed in body.
    with connect(Path(citizens_db)) as conn:
        result = house_post.route_via_cos(
            conn,
            from_id=COS_ID,
            assignee_id=peer,
            body=body,
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
        "state": "working",
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


REPLIED_MARKER = "⟦room:replied:{peer}⟧"


def find_room_for_commission(
    data_root: Path | str, commission_id: str
) -> dict[str, Any] | None:
    """Locate a room sidecar that recorded this commission_id."""
    if not commission_id:
        return None
    root = rooms_root(data_root)
    if not root.is_dir():
        return None
    for p in root.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for ev in data.get("events") or []:
            if ev.get("commission_id") == commission_id:
                return data
    return None


def find_latest_room_for_peer(
    data_root: Path | str, peer: str, *, dm_session_id: str | None = None
) -> dict[str, Any] | None:
    peer = (peer or "").strip().lower()
    root = rooms_root(data_root)
    if not root.is_dir() or peer not in PEERS:
        return None
    best = None
    best_at = ""
    for p in root.glob("*.json"):
        try:
            data = _normalize_room(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
        if peer not in room_peers(data):
            continue
        if dm_session_id and data.get("dm_session_id") not in (None, dm_session_id):
            continue
        at = data.get("created_at") or ""
        events = data.get("events") or []
        if events:
            at = max(at, max((e.get("at") or "") for e in events))
        if at >= best_at:
            best_at = at
            best = data
    return best


def record_house_post_collab(
    conv: ConversationStore,
    *,
    data_root: Path | str,
    from_id: str,
    to_id: str,
    body: str,
    dm_session_id: str | None,
    room_session_id: str | None = None,
    commission_id: str | None = None,
    mark_working: bool = False,
) -> dict[str, Any] | None:
    """When CoS↔peer house_post fires during a chat, project into DM chip + room.

    Returns event dict if recorded, else None.
    """
    from_id = (from_id or "").strip().lower()
    to_id = (to_id or "").strip().lower()
    body = (body or "").strip()
    if not body:
        return None

    # CoS → peer: open/link room, chip on DM, line in room
    if from_id == COS_ID and to_id in PEERS:
        peer = to_id
        room = open_room(
            conv,
            data_root=data_root,
            peer=peer,
            dm_session_id=dm_session_id,
            session_id=room_session_id,
        )
        sid = room["session_id"]
        marker = MESSAGED_MARKER.format(peer=peer)
        excerpt = body if len(body) <= 800 else body[:797] + "…"
        is_working = bool(commission_id) or mark_working
        working = " — working…" if is_working else ""
        conv.save_turn(
            sid,
            COS_ID,
            "assistant",
            f"[To {peer.title()}]\n{excerpt}",
            source="room",
        )
        if is_working:
            label = (
                f"Commissioned {peer.title()} · `{commission_id[:8]}` — waiting on reply."
                if commission_id
                else f"Looped in {peer.title()} — waiting on reply."
            )
            conv.save_turn(
                sid,
                COS_ID,
                "system",
                label,
                source="room",
            )
        if dm_session_id and conv.get_session(dm_session_id) is not None:
            conv.save_turn(
                dm_session_id,
                COS_ID,
                "system",
                f"{marker} Messaged {peer.title()}{working}",
                source="room",
            )
        event = {
            "type": "messaged_peer",
            "peer": peer,
            "at": _utc_now(),
            "brief": excerpt[:200],
            "room_session_id": sid,
            "dm_session_id": dm_session_id,
            "direction": "cos_to_peer",
            "state": "working" if is_working else "messaged",
        }
        if commission_id:
            event["commission_id"] = commission_id
        room.setdefault("events", []).append(event)
        if dm_session_id:
            room["dm_session_id"] = dm_session_id
        _save_room(data_root, room)
        return event

    # Peer → CoS: find rooms for that peer and append peer bubble
    if to_id == COS_ID and from_id in PEERS:
        peer = from_id
        excerpt = body if len(body) <= 800 else body[:797] + "…"
        matched = None
        if room_session_id:
            matched = load_room(data_root, room_session_id)
        if matched is None and commission_id:
            matched = find_room_for_commission(data_root, commission_id)
        if matched is None:
            matched = find_latest_room_for_peer(
                data_root, peer, dm_session_id=dm_session_id
            )
        if matched is None and dm_session_id:
            matched = open_room(
                conv, data_root=data_root, peer=peer, dm_session_id=dm_session_id
            )
        if matched is None:
            return None
        sid = matched["session_id"]
        dm = matched.get("dm_session_id") or dm_session_id
        conv.save_turn(
            sid,
            COS_ID,
            "system",
            f"[From {peer.title()}]\n{excerpt}",
            source="room",
        )
        if dm and conv.get_session(dm) is not None:
            reply_marker = REPLIED_MARKER.format(peer=peer)
            conv.save_turn(
                dm,
                COS_ID,
                "system",
                f"{reply_marker} {peer.title()} replied — open group to read.",
                source="room",
            )
        event = {
            "type": "peer_reply",
            "peer": peer,
            "at": _utc_now(),
            "brief": excerpt[:200],
            "room_session_id": sid,
            "dm_session_id": dm,
            "direction": "peer_to_cos",
        }
        if commission_id:
            event["commission_id"] = commission_id
        matched.setdefault("events", []).append(event)
        _save_room(data_root, matched)
        return event

    return None


def project_commission_result(
    conv: ConversationStore,
    *,
    data_root: Path | str,
    citizen_id: str,
    commission_id: str,
    result_text: str,
    ok: bool = True,
) -> dict[str, Any] | None:
    """After citizens-runtime finishes a commission, land the reply in the room."""
    peer = (citizen_id or "").strip().lower()
    if peer not in PEERS:
        return None
    text = (result_text or "").strip()
    if not text:
        text = "(empty result)" if ok else "(failed with no detail)"
    if not ok:
        text = f"**Failed:**\n{text}"
    # Prefer the room that commissioned this id; fall back to latest peer room.
    room = find_room_for_commission(data_root, commission_id)
    dm = room.get("dm_session_id") if room else None
    return record_house_post_collab(
        conv,
        data_root=data_root,
        from_id=peer,
        to_id=COS_ID,
        body=text,
        dm_session_id=dm,
        room_session_id=room.get("session_id") if room else None,
        commission_id=commission_id,
    )


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
