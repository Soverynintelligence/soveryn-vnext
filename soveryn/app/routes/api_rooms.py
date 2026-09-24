"""Group room APIs — open room, ask peer, collab chips for 1:1 DMs."""

from __future__ import annotations

import os
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request

from soveryn.rooms.store import (
    DEFAULT_PEER,
    PEERS,
    add_peer_to_room,
    ask_peer,
    collabs_for_dm,
    load_room,
    open_room,
    overlay_collab_commission_states,
    peer_commission_status,
    room_peers,
)

bp = Blueprint("api_rooms", __name__)


def _state():
    return current_app.extensions.get("soveryn") or {}


def _data_root() -> Path:
    env = _state().get("env")
    if env is not None and getattr(env, "data_root", None):
        return Path(env.data_root)
    raw = os.environ.get("SOVERYN_DATA_ROOT")
    if raw:
        return Path(raw)
    return Path.home() / "soveryn_vnext" / "data"


def _citizens_db() -> Path:
    configured = (
        current_app.config.get("CITIZENS_DB")
        or os.environ.get("SOVERYN_CITIZENS_DB")
    )
    if configured:
        return Path(configured)
    return Path.home() / "soveryn_vnext" / "data" / "citizens.db"


def _conv():
    store = _state().get("conv_store")
    if store is None:
        raise RuntimeError("conv_store not wired")
    return store


@bp.post("/api/rooms/open")
def api_rooms_open():
    """Create or resume a CoS+peer room. Body: {peer?, dm_session_id?, session_id?}."""
    body = request.get_json(silent=True) or {}
    peer = (body.get("peer") or DEFAULT_PEER).strip().lower()
    dm = body.get("dm_session_id")
    sid = body.get("session_id")
    if peer not in PEERS:
        return jsonify({
            "error": {
                "code": "bad_peer",
                "message": f"peer must be one of {sorted(PEERS)}",
            }
        }), 400
    try:
        room = open_room(
            _conv(),
            data_root=_data_root(),
            peer=peer,
            dm_session_id=dm.strip() if isinstance(dm, str) and dm.strip() else None,
            session_id=sid.strip() if isinstance(sid, str) and sid.strip() else None,
        )
    except ValueError as exc:
        return jsonify({"error": {"code": "open_failed", "message": str(exc)}}), 400
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": {"code": "open_failed", "message": str(exc)}}), 500
    peers = room_peers(room)
    primary = peers[0] if peers else room.get("peer") or peer
    return jsonify({
        "ok": True,
        "room": room,
        "url": f"/room?session={room['session_id']}&peer={primary}",
    }), 200


@bp.get("/api/rooms/<session_id>")
def api_rooms_get(session_id: str):
    room = load_room(_data_root(), session_id)
    if room is None:
        return jsonify({"error": {"code": "not_found", "message": "no room"}}), 404
    # Attach latest commission statuses for events
    events = []
    for ev in room.get("events") or []:
        e = dict(ev)
        cid = e.get("commission_id")
        if cid:
            row = peer_commission_status(_citizens_db(), cid)
            if row:
                e["commission_state"] = row.get("state")
                e["commission_error"] = row.get("error")
        events.append(e)
    out = {**room, "events": events, "peers": room_peers(room)}
    return jsonify({"ok": True, "room": out}), 200


@bp.post("/api/rooms/<session_id>/add_peer")
def api_rooms_add_peer(session_id: str):
    """Add Eve/Scotty/… to an existing group thread."""
    body = request.get_json(silent=True) or {}
    peer = (body.get("peer") or "").strip().lower()
    if peer not in PEERS:
        return jsonify({
            "error": {
                "code": "bad_peer",
                "message": f"peer must be one of {sorted(PEERS)}",
            }
        }), 400
    try:
        room = add_peer_to_room(
            _conv(),
            data_root=_data_root(),
            session_id=session_id,
            peer=peer,
        )
    except ValueError as exc:
        return jsonify({"error": {"code": "add_failed", "message": str(exc)}}), 400
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": {"code": "add_failed", "message": str(exc)}}), 500
    return jsonify({"ok": True, "room": room, "peers": room_peers(room)}), 200


@bp.post("/api/rooms/<session_id>/ask_peer")
def api_rooms_ask_peer(session_id: str):
    body = request.get_json(silent=True) or {}
    brief = body.get("brief") or body.get("message") or ""
    if not isinstance(brief, str) or not brief.strip():
        return jsonify({
            "error": {"code": "missing_field", "message": "brief required"},
        }), 400
    db = _citizens_db()
    if not db.exists():
        return jsonify({
            "error": {
                "code": "no_registry",
                "message": "citizens registry missing — run census",
            }
        }), 503
    peer = body.get("peer")
    if isinstance(peer, str):
        peer = peer.strip().lower() or None
    else:
        peer = None
    try:
        result = ask_peer(
            _conv(),
            data_root=_data_root(),
            citizens_db=db,
            session_id=session_id,
            brief=brief.strip(),
            from_id=(body.get("from_id") or "jon"),
            peer=peer,
        )
    except ValueError as exc:
        return jsonify({"error": {"code": "ask_failed", "message": str(exc)}}), 400
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": {"code": "ask_failed", "message": str(exc)}}), 500
    return jsonify(result), 200


@bp.get("/api/rooms/collabs")
def api_rooms_collabs():
    """Collab chips for a 1:1 DM session (?dm_session_id=)."""
    dm = (request.args.get("dm_session_id") or "").strip()
    if not dm:
        return jsonify({"error": {"code": "missing_field", "message": "dm_session_id"}}), 400
    root = _data_root()
    events = overlay_collab_commission_states(
        collabs_for_dm(root, dm),
        citizens_db=_citizens_db(),
        data_root=root,
        persist=True,
    )
    return jsonify({"ok": True, "collabs": events, "count": len(events)}), 200
