"""read_collab — Aetheria inspects a live or closed peer collab."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable

from soveryn.platform.tools.registry import ToolArgError, ToolSpec
from soveryn.rooms.store import PEERS, collab_is_active, collabs_for_dm, peer_commission_status


def build_read_collab_tool(
    *,
    owner_agent: str = "aetheria",
    conv_store=None,
    data_root: Path | str | None = None,
    citizens_db: Path | str | None = None,
    conv_getter: Callable[[], Any] | None = None,
    root_getter: Callable[[], Path | str | None] | None = None,
) -> ToolSpec:
    def handler(args: Mapping[str, Any]) -> dict[str, Any]:
        peer = (args.get("peer") or "").strip().lower()
        if peer not in PEERS:
            raise ToolArgError(f"peer must be one of {sorted(PEERS)}, got {peer!r}")
        cid = (args.get("commission_id") or "").strip() or None
        root = data_root
        if root is None and root_getter is not None:
            root = root_getter()
        if root is None:
            try:
                from soveryn.rooms import context as room_ctx

                root = room_ctx.data_root.get()
            except Exception:
                root = None
        conv = conv_store
        if conv is None and conv_getter is not None:
            conv = conv_getter()
        if conv is None:
            try:
                from flask import current_app

                conv = (current_app.extensions.get("soveryn") or {}).get("conv_store")
            except Exception:
                conv = None
        db = citizens_db or Path(
            os.environ.get("SOVERYN_CITIZENS_DB")
            or (Path.home() / "soveryn_vnext" / "data" / "citizens.db")
        )
        if not root:
            return {"ok": False, "error": "no data_root"}
        dm = None
        try:
            from soveryn.rooms import context as room_ctx

            dm = room_ctx.dm_session_id.get()
        except Exception:
            dm = None
        events = collabs_for_dm(root, dm) if dm else []
        if not events:
            # Fall back: all rooms for this peer via glob of collabs isn't
            # keyed without dm. Scan events from every sidecar is heavy;
            # require dm or commission_id.
            from soveryn.rooms.store import find_room_for_commission, rooms_root
            import json

            if cid:
                room = find_room_for_commission(root, cid)
                if room:
                    events = [
                        {**e, "room_session_id": room.get("session_id")}
                        for e in (room.get("events") or [])
                        if e.get("type") == "messaged_peer"
                    ]
            else:
                events = []
                rroot = rooms_root(root)
                for p in rroot.glob("*.json"):
                    try:
                        data = json.loads(p.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        continue
                    for e in data.get("events") or []:
                        if (
                            e.get("type") == "messaged_peer"
                            and (e.get("peer") or "").strip().lower() == peer
                        ):
                            events.append({**e, "room_session_id": data.get("session_id")})
        hit = None
        for ev in events:
            if (ev.get("peer") or "").strip().lower() != peer:
                continue
            if cid and ev.get("commission_id") != cid:
                continue
            hit = ev
            break
        if hit is None:
            return {"ok": False, "error": "no collab", "peer": peer}
        row = peer_commission_status(db, hit.get("commission_id") or "")
        turns: list[dict[str, str]] = []
        room_sid = hit.get("room_session_id")
        if conv is not None and room_sid:
            for t in conv.load_history(room_sid)[-12:]:
                turns.append({"role": t.role, "content": (t.content or "")[:800]})
        return {
            "ok": True,
            "peer": peer,
            "commission_id": hit.get("commission_id"),
            "state": (hit.get("state") or ""),
            "active": collab_is_active(hit, commission_row=row),
            "commission_state": (row or {}).get("state"),
            "error": (row or {}).get("error"),
            "result_ref": (row or {}).get("result_ref"),
            "room_session_id": room_sid,
            "turns": turns,
        }

    schema = {
        "type": "object",
        "properties": {
            "peer": {
                "type": "string",
                "description": "kernel or eve",
            },
            "commission_id": {
                "type": "string",
                "description": "Optional commission id. Omit for the latest collab with that peer.",
            },
        },
        "required": ["peer"],
        "additionalProperties": False,
    }
    return ToolSpec(
        name="read_collab",
        owner=owner_agent,
        schema=schema,
        handler=handler,
        description=(
            "Inspect a Kernel/Eve collab: state, ticket, last room turns. "
            "If state is working, read this instead of re-dispatching. "
            "If done or failed, brief Jon from the transcript."
        ),
    )
