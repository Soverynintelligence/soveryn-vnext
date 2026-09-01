"""Room sidecars + ask_peer (house_post / commission) for group chat v0."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from soveryn.memory.conversation_store import ConversationStore

# Pickable peers (not CoS). Default Eve.
# Fleet freeze 2026-08-27: CoS commissions go to Eve/Kernel only.
# Vett/Scotty parked — not commission peers (engine room only).
PEERS: frozenset[str] = frozenset({"eve", "kernel"})
DEFAULT_PEER = "eve"
COS_ID = "aetheria"

# Marker embedded in 1:1 system turns so chat.html can render a chip.
MESSAGED_MARKER = "⟦room:messaged:{peer}⟧"
CLOSED_MARKER = "⟦room:closed:{peer}⟧"
# Desk stops calling a collab "working" after this even if the ticket is still
# running. Ticket lifetime is separate (runtime requeue / abandon).
COLLAB_TTL_SECONDS = 45 * 60


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



def _close_matching_messaged_peer(
    room: dict[str, Any],
    *,
    peer: str,
    commission_id: str | None,
    ok: bool,
) -> bool:
    """Flip matching messaged_peer chip to done/failed. True if patched."""
    events = room.get("events") or []
    terminal = "done" if ok else "failed"
    hit = None
    cid = (commission_id or "").strip()
    peer_l = (peer or "").strip().lower()
    if cid:
        for ev in reversed(events):
            if ev.get("type") == "messaged_peer" and ev.get("commission_id") == cid:
                hit = ev
                break
    if hit is None:
        for ev in reversed(events):
            if (
                ev.get("type") == "messaged_peer"
                and (ev.get("peer") or "").strip().lower() == peer_l
                and (ev.get("state") or "").strip().lower() == "working"
            ):
                hit = ev
                break
    if hit is None:
        return False
    if (hit.get("state") or "").strip().lower() in ("done", "failed"):
        return False
    hit["state"] = terminal
    return True


def _parse_at(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip()
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def collab_is_active(
    ev: dict[str, Any],
    *,
    now: datetime | None = None,
    commission_row: dict[str, Any] | None = None,
) -> bool:
    """True only while the desk should show this collab as live."""
    if not ev or not ev.get("peer"):
        return False
    st = (ev.get("state") or "").strip().lower()
    live = ((commission_row or {}).get("state") or "").strip().lower()
    if st in ("done", "failed") or live in ("done", "failed"):
        return False
    clock = now or datetime.now(timezone.utc)
    at = _parse_at(ev.get("at") if isinstance(ev.get("at"), str) else None)
    aged_out = bool(
        at is not None and (clock - at).total_seconds() > COLLAB_TTL_SECONDS
    )
    if live in ("queued", "running"):
        return not aged_out
    if st == "working":
        if at is None:
            return False
        return not aged_out
    return False


def find_open_collab(
    data_root: Path | str,
    *,
    dm_session_id: str,
    peer: str,
    citizens_db: Path | str | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Live working collab for this 1:1 + peer, if any."""
    peer_l = (peer or "").strip().lower()
    if not dm_session_id or peer_l not in PEERS:
        return None
    for ev in collabs_for_dm(data_root, dm_session_id):
        if (ev.get("peer") or "").strip().lower() != peer_l:
            continue
        cid = ev.get("commission_id")
        if not cid:
            continue
        row = None
        if citizens_db is not None:
            row = peer_commission_status(citizens_db, cid)
            if row is not None and (row.get("state") or "") not in ("queued", "running"):
                continue
        if collab_is_active(ev, now=now, commission_row=row):
            return ev
    return None


def close_collab_for_commission(
    conv: ConversationStore,
    *,
    data_root: Path | str,
    commission_id: str,
    ok: bool = True,
    peer: str | None = None,
) -> dict[str, Any] | None:
    """Persist chip done/failed and write a terminal DM line. Idempotent."""
    cid = (commission_id or "").strip()
    if not cid:
        return None
    room = find_room_for_commission(data_root, cid)
    if room is None:
        return None
    peer_l = (peer or "").strip().lower()
    if not peer_l:
        for ev in reversed(room.get("events") or []):
            if ev.get("commission_id") == cid:
                peer_l = (ev.get("peer") or "").strip().lower()
                break
    if not peer_l:
        peers = room_peers(room)
        peer_l = peers[0] if peers else ""
    if not peer_l:
        return None
    _close_matching_messaged_peer(
        room, peer=peer_l, commission_id=cid, ok=ok
    )
    dm = room.get("dm_session_id")
    marker = CLOSED_MARKER.format(peer=peer_l)
    terminal = "done" if ok else "failed"
    if dm and conv.get_session(dm) is not None:
        already = any(
            marker in (t.content or "")
            for t in conv.load_history(dm)
            if t.role == "system"
        )
        if not already:
            conv.save_turn(
                dm,
                COS_ID,
                "system",
                f"{marker} {peer_l.title()} {terminal}",
                source="room",
            )
    _save_room(data_root, room)
    return room


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
        # Working requires a commission ticket. mark_working without an id
        # used to paint an immortal chip the overlay could never close.
        is_working = bool(commission_id)
        working = " — waiting on reply" if is_working else ""
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
        # Longer body in the shared room so the group sees the raw work.
        room_excerpt = body if len(body) <= 4000 else body[:3997] + "…"
        conv.save_turn(
            sid,
            COS_ID,
            "system",
            f"[From {peer.title()}]\n{room_excerpt}",
            source="room",
        )
        # Chip + short interim: CoS will summarize into the DM (not a raw dump).
        ok = not body.lstrip().startswith("**Failed:**")
        name = peer.title()
        if dm and conv.get_session(dm) is not None:
            reply_marker = REPLIED_MARKER.format(peer=peer)
            conv.save_turn(
                dm,
                COS_ID,
                "system",
                f"{reply_marker} {name} replied — open group for the thread.",
                source="room",
            )
            conv.save_turn(
                dm,
                COS_ID,
                "assistant",
                (
                    f"{name} is back"
                    f"{'' if ok else ' (with problems)'}. "
                    f"I'm summarizing for you now."
                ),
                source="cos_relay",
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
        _close_matching_messaged_peer(
            matched, peer=peer, commission_id=commission_id, ok=ok
        )
        _save_room(data_root, matched)
        return event

    return None


def _resolve_jon_dm_session(
    conv: ConversationStore, dm_session_id: str | None
) -> str | None:
    """Prefer the linked DM; never deliver into heartbeat/automation shells."""
    def _usable(sid: str | None) -> str | None:
        if not sid:
            return None
        meta = conv.get_session(sid)
        if meta is None:
            return None
        title = (meta.title or "").strip()
        if title.startswith("[heartbeat]") or title.startswith("automation:"):
            return None
        if title.startswith("[room:"):
            return None
        return sid

    hit = _usable(dm_session_id)
    if hit:
        return hit
    for s in conv.list_sessions(agent=COS_ID, limit=40):
        t = (s.title or "").strip()
        if t.startswith("[m]"):
            return s.session_id
    for s in conv.list_sessions(agent=COS_ID, limit=40):
        if _usable(s.session_id):
            return s.session_id
    return None


_THIN_COS_META = re.compile(
    r"brief is in front|objective closed|waiting on (?:his|jon)|"
    r"numbers work or he wants changes|full detail from .+ is in the group",
    re.IGNORECASE,
)


def _extract_price_block(peer_result: str) -> str:
    """Pull a markdown price table (or $-lines) out of a peer result."""
    text = peer_result or ""
    lines = text.splitlines()
    # Prefer a markdown table that mentions Price.
    for i, line in enumerate(lines):
        if "|" in line and re.search(r"price", line, re.I):
            block = [line]
            if i + 1 < len(lines) and re.match(r"^\s*\|?\s*-+", lines[i + 1]):
                block.append(lines[i + 1])
                j = i + 2
            else:
                j = i + 1
            while j < len(lines) and "|" in lines[j]:
                block.append(lines[j])
                j += 1
            joined = "\n".join(block).strip()
            if "$" in joined and len(block) >= 3:
                return joined
    money = [ln for ln in lines if "$" in ln and ln.strip()]
    if money:
        return "\n".join(money[:12])
    return ""


def ensure_cos_brief_carries_numbers(summary: str, peer_result: str) -> str:
    """If the peer found dollars and CoS dropped them, put the table back.

    Live failure mode (2026-08-23): CoS wrote 'Objective closed. Brief is in
    front of Jon' with zero $ while Vett's room result had the Apex table.
    """
    summary = (summary or "").strip()
    peer = (peer_result or "").strip()
    if "$" not in peer:
        return summary
    thin = bool(_THIN_COS_META.search(summary)) if summary else True
    if "$" in summary and not thin:
        return summary
    block = _extract_price_block(peer)
    if not block:
        return summary
    lead = (
        "Vett finished the house-catalog dig. Here's what you can quote:"
        if thin or not summary
        else summary.rstrip()
    )
    if thin and summary and "$" not in summary:
        lead = "Vett finished the house-catalog dig. Here's what you can quote:"
    return (
        f"{lead}\n\n"
        f"**Numbers from Vett (house catalogs):**\n\n"
        f"{block}"
    )


def deliver_peer_result_to_jon(
    conv: ConversationStore,
    *,
    dm_session_id: str | None,
    peer: str,
    result_text: str,
    ok: bool = True,
    commission_id: str | None = None,
    room_session_id: str | None = None,
    as_cos_summary: bool = False,
    peer_result_for_numbers: str | None = None,
) -> bool:
    """Deliver into Jon's 1:1 DM — preferably Aetheria's CoS summary.

    When ``as_cos_summary`` is True, ``result_text`` is already Aetheria's
    synthesis (Chief of Staff voice). Otherwise treat as raw peer dump
    (legacy / fallback).
    """
    peer = (peer or "").strip().lower()
    dm = _resolve_jon_dm_session(conv, dm_session_id)
    if not dm:
        return False
    text = (result_text or "").strip() or ("(empty result)" if ok else "(failed)")
    if as_cos_summary and peer_result_for_numbers:
        text = ensure_cos_brief_carries_numbers(text, peer_result_for_numbers)
    # Cap for chat readability; full text stays in room + outbox.
    delivery = text if len(text) <= 3500 else text[:3497] + "…"
    name = peer.title() if peer else "Peer"
    if as_cos_summary:
        msg = delivery
        if room_session_id and name and "tap their shape" not in msg.lower():
            msg += (
                f"\n\n_Full detail from {name} is in the group "
                f"(tap their shape if you want the raw thread)._"
            )
    elif ok:
        msg = (
            f"{name} finished — my take for you:\n\n"
            f"{delivery}"
        )
    else:
        msg = (
            f"{name} hit a wall — my take:\n\n"
            f"{delivery}"
        )
    conv.save_turn(dm, COS_ID, "assistant", msg, source="cos_relay")
    # Best-effort Signal ping so the phone buzzes without waiting on chat UI.
    try:
        _signal_cos_ping(
            peer=peer,
            ok=ok,
            preview=delivery[:500],
            commission_id=commission_id,
        )
    except Exception:
        pass
    return True


COS_RELAY_MARKER = "[COS_RELAY]"


def build_cos_relay_brief(
    *,
    peer: str,
    source_commission_id: str,
    task: str,
    result_text: str,
    ok: bool,
    dm_session_id: str | None,
    room_session_id: str | None,
) -> str:
    """Prompt body for Aetheria's summarize-and-deliver commission."""
    import re

    peer = (peer or "").strip().lower()
    result = (result_text or "").strip()
    if len(result) > 8000:
        result = result[:7997] + "…"
    task = (task or "").strip()
    if len(task) > 1200:
        task = task[:1197] + "…"
    status = "ok" if ok else "failed"

    verify_block = ""
    oid = None
    m = re.search(
        r"\[RESEARCH_OBJECTIVE ([0-9a-fA-F-]{36})\]", task
    ) or re.search(
        r"OBJECTIVE_ID:\s*([0-9a-fA-F-]{36})", result
    )
    if m:
        oid = m.group(1)
    if oid or "ready_for_verify" in result.lower() or "[RESEARCH_OBJECTIVE" in task:
        verify_block = (
            "\n## Standing objective — verify step\n"
            "This was assign→execute work. Deliver your brief to Jon **now**.\n"
            "**Do NOT** call objective_verify in this turn — wait until Jon "
            "explicitly accepts or rejects in a later message.\n"
            f"When he does, call objective_verify with objective_id="
            f"`{oid or '(from OBJECTIVE_ID in result)'}` and state "
            "`done`|`failed`|`cancelled` plus a one-line note.\n"
        )

    return (
        f"{COS_RELAY_MARKER}\n"
        f"peer: {peer}\n"
        f"source_commission: {source_commission_id}\n"
        f"dm_session_id: {dm_session_id or '-'}\n"
        f"room_session_id: {room_session_id or '-'}\n"
        f"ok: {status}\n\n"
        "You are Aetheria — philosophical partner briefing Jon on peer work. "
        "You are not managing him or the house; you are synthesizing so he can "
        "see the result without digging the group thread.\n"
        "- Lead with the substance (what was found / built / blocked).\n"
        "- Keep specific prices, models, and sources when the peer found them "
        "(copy the useful table rows into your brief — Jon should not need the "
        "group thread to see dollar amounts).\n"
        "- Call out gaps honestly (what is still unknown).\n"
        "- Flag a decision only when one is actually required — do not invent "
        "urgency or boss him.\n"
        "- Do not invent numbers. Do not paste the peer's report wholesale.\n"
        "- Aim for a tight partner brief.\n"
        "- Your reply IS the brief delivered to Jon's DM — never say "
        "'brief is in front of him' without writing the numbers.\n"
        f"{verify_block}\n"
        f"## Peer task\n{task}\n\n"
        f"## Peer result\n{result}\n"
    )


def parse_cos_relay_brief(body: str) -> dict[str, str] | None:
    """Parse [COS_RELAY] metadata from an Aetheria commission body."""
    text = (body or "").strip()
    if not text.startswith(COS_RELAY_MARKER):
        return None
    meta: dict[str, str] = {}
    rest = text[len(COS_RELAY_MARKER) :].lstrip("\n")
    lines = rest.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            break
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip().lower()] = v.strip()
        i += 1
    return meta


def _signal_cos_ping(
    *,
    peer: str,
    ok: bool,
    preview: str,
    commission_id: str | None,
) -> None:
    """Optional Direct Line nudge — fail open if Signal isn't armed."""
    import os

    if os.environ.get("SOVERYN_COS_RELAY_SIGNAL", "1").strip() in ("0", "false", "no"):
        return
    try:
        from soveryn.agents.signal_bridge.client import send_once
        from soveryn.agents.signal_bridge.config import SignalBridgeConfig
    except Exception:
        return
    try:
        cfg = SignalBridgeConfig.from_env()
    except Exception:
        return
    if not cfg.bot_number or not cfg.allowed_numbers:
        return
    recipient = sorted(cfg.allowed_numbers)[0]
    name = peer.title()
    head = f"Aetheria · {name} {'done' if ok else 'failed'}"
    if commission_id:
        head += f" (`{commission_id[:8]}`)"
    body = f"{head}\n\n{preview}\n\n— full write-up is in your Aetheria chat / group."
    try:
        send_once(
            signal_cli_bin=cfg.signal_cli_bin,
            bot_number=cfg.bot_number,
            recipient_e164=recipient,
            body=body,
        )
    except Exception:
        return


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



def overlay_collab_commission_states(
    events: list[dict[str, Any]],
    *,
    citizens_db: Path | str,
    data_root: Path | str | None = None,
    persist: bool = True,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Attach commission_state; close leftover working chips when ended or TTL."""
    out: list[dict[str, Any]] = []
    rooms_to_save: dict[str, dict[str, Any]] = {}
    terminal = {"done", "failed"}
    clock = now or datetime.now(timezone.utc)
    for ev in events:
        e = dict(ev)
        cid = e.get("commission_id")
        row = peer_commission_status(citizens_db, cid) if cid else None
        if row:
            e["commission_state"] = row.get("state")
            e["commission_error"] = row.get("error")
        sidecar = (e.get("state") or "").strip().lower()
        live = ((row or {}).get("state") or "").strip().lower()
        should_close = sidecar == "working" and (
            live in terminal
            or not collab_is_active(e, now=clock, commission_row=row)
        )
        if should_close:
            new_state = live if live in terminal else "failed"
            e["state"] = new_state
            if new_state == "failed" and live not in terminal:
                e["commission_error"] = e.get("commission_error") or "ttl_expired"
            sid = e.get("room_session_id")
            if persist and data_root and sid:
                room = rooms_to_save.get(sid)
                if room is None:
                    room = load_room(data_root, sid)
                if room is not None:
                    patched = False
                    for orig in room.get("events") or []:
                        if orig.get("type") != "messaged_peer":
                            continue
                        if cid and orig.get("commission_id") != cid:
                            continue
                        if not cid and orig is not ev:
                            if orig.get("at") != e.get("at"):
                                continue
                        if (orig.get("state") or "").strip().lower() != "working":
                            continue
                        orig["state"] = new_state
                        patched = True
                    if patched:
                        rooms_to_save[sid] = room
        out.append(e)
    if persist and data_root:
        for room in rooms_to_save.values():
            _save_room(data_root, room)
    return out


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
