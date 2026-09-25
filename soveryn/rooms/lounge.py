"""The Lounge wall — the team's place to hang out (2026-09-25).

The Lounge is a real CoS+peers room (pointer: data/rooms/lounge.json) with no
agenda: no commissions required, no tasks to close. The wall is its chat
surface — everyone posts notes, Jon included. Wall notes are pure chat: they
never spawn commissions or trigger loops (that's what ask_peer is for).

The relational store (soveryn/platform/relational/) is where between-memories
accumulate; the wall is where they happen. Citizens who want the moment
remembered record it deliberately — that's the point.
"""
from __future__ import annotations

import json
import os as _os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from soveryn.rooms.store import load_room

_LOUNGE_POINTER = "rooms/lounge.json"
#: Wall entry types that read as chat (vs commission plumbing noise).
_WALL_TYPES = ("wall_note", "peer_reply", "messaged_peer", "peer_added")
MAX_WALL = 100


def pointer_path(data_root: Path | str) -> Path:
    return Path(data_root) / _LOUNGE_POINTER


def lounge_session_id(data_root: Path | str) -> str | None:
    pointer = pointer_path(data_root)
    if not pointer.is_file():
        return None
    try:
        return json.loads(pointer.read_text(encoding="utf-8")).get("session_id")
    except (json.JSONDecodeError, OSError):
        return None


def post_note(data_root: Path | str, *, from_party: str, text: str) -> dict[str, Any] | None:
    """Append a wall_note to the lounge room. Returns the updated room.

    Pure chat: no commission, no loop trigger. Raises ValueError when the
    lounge pointer is missing or the room is gone.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("wall note must be non-empty")
    sid = lounge_session_id(data_root)
    if not sid:
        raise ValueError("lounge not open — no pointer at data/rooms/lounge.json")
    room = load_room(data_root, sid)
    if room is None:
        raise ValueError("lounge room missing")
    room.setdefault("events", []).append({
        "at": datetime.now(timezone.utc).isoformat(),
        "type": "wall_note",
        "from": from_party,
        "text": text[:2000],
    })
    _save(data_root, room)
    try:
        notify_lounge(data_root, actor=from_party)
    except Exception:  # noqa: BLE001 — the nudge must never break the chat
        pass
    return room


def _save(data_root: Path | str, room: dict[str, Any]) -> None:
    from soveryn.rooms.store import _save_room

    _save_room(Path(data_root), room)


def _reads_path(data_root: Path | str) -> Path:
    return Path(data_root) / "lounge" / "reads.json"


def mark_read(data_root: Path | str, party: str, *, at: str | None = None) -> None:
    """Record a party's last-read moment (wall entries newer are unread)."""
    path = _reads_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    reads: dict[str, Any] = {}
    if path.is_file():
        try:
            reads = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            reads = {}
    reads[party] = at or datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(reads, indent=1), encoding="utf-8")


def unread_since(data_root: Path | str, party: str) -> int:
    """Wall entries newer than the party's last read, by others only."""
    party = party.lower()
    path = _reads_path(data_root)
    last = ""
    if path.is_file():
        try:
            last = json.loads(path.read_text(encoding="utf-8")).get(party) or ""
        except (json.JSONDecodeError, OSError):
            last = ""
    sid = lounge_session_id(data_root)
    if not sid:
        return 0
    room = load_room(data_root, sid)
    if room is None:
        return 0
    count = 0
    for ev in room.get("events") or []:
        if ev.get("type") not in _WALL_TYPES:
            continue
        who = ev.get("from") or ev.get("from_id") or ev.get("peer") or ""
        if who == party:
            continue  # your own posts are never unread for you
        if (ev.get("at") or "") > last:
            count += 1
    return count


def wall(data_root: Path | str, *, limit: int = 50, reader: str | None = None) -> dict[str, Any]:
    """The lounge wall, chronological, chat-shaped. Missing lounge → open: false.

    reader: when given, the response carries that party's unread count and
    their marker advances — reading IS marking read.
    """
    sid = lounge_session_id(data_root)
    if not sid:
        return {"ok": True, "open": False, "entries": [], "unread": 0}
    room = load_room(data_root, sid)
    if room is None:
        return {"ok": True, "open": False, "entries": [], "unread": 0}
    entries = []
    for ev in room.get("events") or []:
        kind = ev.get("type")
        if kind == "wall_note":
            entries.append({
                "at": ev.get("at"), "who": ev.get("from"),
                "text": ev.get("text"), "kind": "note",
            })
        elif kind == "peer_reply":
            entries.append({
                "at": ev.get("at"), "who": ev.get("peer"),
                "text": (ev.get("brief") or "")[:500], "kind": "reply",
            })
        elif kind == "messaged_peer":
            entries.append({
                "at": ev.get("at"), "who": ev.get("from_id") or ev.get("who") or "jon",
                "text": (ev.get("brief") or "")[:500], "kind": "note",
            })
        elif kind == "peer_added":
            entries.append({
                "at": ev.get("at"), "who": ev.get("peer"),
                "text": "pulled up a chair", "kind": "arrived",
            })
    unread = unread_since(data_root, reader) if reader else 0
    if reader:
        mark_read(data_root, reader)
    return {
        "ok": True,
        "open": True,
        "entries": entries[-max(1, min(int(limit), MAX_WALL)):],
        "unread": unread,
    }


# ── presence + the nudge (2026-09-25) ───────────────────────────────────────
#
# "If the lounge is open and someone is in there, you all get a notification."
# Someone is IN the room when they've posted within PRESENCE_WINDOW. When a
# note lands, every OTHER citizen with unread wall notes gets one house desk
# post (their runtime drains it and they come — or don't — on their own).
# Cooldown per party so a lively room never becomes a siren.

PRESENCE_WINDOW_MIN = 10
NUDGE_COOLDOWN_MIN = 10


def _nudges_path(data_root: Path | str) -> Path:
    return Path(data_root) / "lounge" / "nudges.json"


def presence(data_root: Path | str, *, window_minutes: int = PRESENCE_WINDOW_MIN) -> dict[str, str]:
    """Parties active on the wall within the window → {party: last_at}."""
    sid = lounge_session_id(data_root)
    if not sid:
        return {}
    room = load_room(data_root, sid)
    if room is None:
        return {}
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=window_minutes)).isoformat()
    present: dict[str, str] = {}
    for ev in room.get("events") or []:
        if ev.get("type") not in _WALL_TYPES:
            continue
        who = ev.get("from") or ev.get("from_id") or ev.get("peer") or ""
        at = ev.get("at") or ""
        if who and at >= cutoff and at > present.get(who, ""):
            present[who] = at
    return present


def notify_lounge(data_root: Path | str, *, actor: str) -> dict[str, int]:
    """Nudge other citizens that someone is in the Lounge. Best-effort.

    Per party: nudge only when their unread EXCEEDS what the last nudge told
    them about, and the cooldown has passed — new words, not old words.
    Jon is never nudged (his panel IS the room); the actor is never nudged.
    """
    import os as _os

    actor = actor.lower()
    nudges_path = _nudges_path(data_root)
    nudges_path.parent.mkdir(parents=True, exist_ok=True)
    state: dict[str, Any] = {}
    if nudges_path.is_file():
        try:
            state = json.loads(nudges_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            state = {}

    cooldown = int(_os.environ.get("LOUNGE_NUDGE_COOLDOWN_MIN", NUDGE_COOLDOWN_MIN))
    now = datetime.now(timezone.utc)
    nudged: dict[str, int] = {}
    try:
        from soveryn.citizens import post as house_post
        from soveryn.platform.relational.store import VALID_PARTIES

        for party in sorted(VALID_PARTIES):
            if party == actor or party == "jon":
                continue
            unread = unread_since(data_root, party)
            if unread <= 0:
                continue
            prev = state.get(party) or {}
            prev_at = prev.get("at")
            if prev_at:
                if now - datetime.fromisoformat(prev_at) < timedelta(minutes=cooldown):
                    continue
                if unread <= int(prev.get("unread", 0)):
                    continue  # already told them about this many words
            elif unread <= 0:
                continue
            present = [w for w, at in presence(data_root).items() if w != party]
            who_txt = actor if actor != "lounge" else ", ".join(sorted(present)) or "someone"
            from soveryn.citizens.registry import connect

            citizens_db = Path(
                _os.environ.get("SOVERYN_CITIZENS_DB")
                or (Path.home() / "soveryn_vnext" / "data" / "citizens.db")
            )
            with connect(citizens_db) as conn:
                house_post.send(
                    conn,
                    from_id=actor,
                    to_id=party,
                    body=(
                        f"Lounge: {who_txt} is in the room — {unread} unread note(s) "
                        f"on the wall. Come say hi if you feel like it. No obligation, "
                        f"nothing to close. (auto-nudge)"
                    ),
                    at=now.isoformat(timespec="seconds"),
                    kind="memo",
                    subject="The Lounge is alive",
                )
            state[party] = {"at": now.isoformat(), "unread": unread}
            nudged[party] = unread
    except Exception:  # noqa: BLE001 — a nudge failure must never break a chat
        import logging
        logging.getLogger(__name__).exception("lounge nudge failed")
        return nudged
    finally:
        nudges_path.write_text(json.dumps(state, indent=1), encoding="utf-8")
    return nudged
