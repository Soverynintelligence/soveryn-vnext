"""Tools so agents can use House Post from inside AgentLoop."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from soveryn.citizens import post as house_post
from soveryn.citizens.registry import connect
from soveryn.platform.tools.registry import ToolRegistry, ToolSpec

_DEFAULT_DB = Path.home() / "soveryn_vnext" / "data" / "citizens.db"

# CoS → peer kinds that should enqueue real work (not just desk mail).
_WORK_KINDS = frozenset({"request", "directive", "memo"})


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _db() -> Path:
    import os
    return Path(os.environ.get("SOVERYN_CITIZENS_DB") or _DEFAULT_DB)


def register_house_post_tools(registry: ToolRegistry, *, owner_agent: str) -> None:
    def send(args: Mapping[str, Any]) -> dict[str, Any]:
        to_id = (args.get("to_id") or "").strip().lower()
        body = (args.get("body") or "").strip()
        kind = (args.get("kind") or "request").strip()
        subject = (args.get("subject") or "").strip() or None
        if not to_id or not body:
            return {"ok": False, "error": "to_id and body required"}
        try:
            from soveryn.rooms.store import PEERS, record_house_post_collab

            when = _now()
            commission_id = None
            with connect(_db()) as conn:
                # Aetheria asking a peer to do work must hit the commission
                # queue — bare house_post is silent mail and Vett never wakes.
                if (
                    owner_agent == house_post.CHIEF_OF_STAFF_ID
                    and to_id in PEERS
                    and kind in _WORK_KINDS
                ):
                    if kind == "memo":
                        kind = "request"
                    routing = house_post.route_via_cos(
                        conn,
                        from_id=owner_agent,
                        assignee_id=to_id,
                        body=body,
                        at=when,
                        subject=subject,
                    )
                    pid = routing.get("directive_post_id") or ""
                    commission_id = routing.get("commission_id")
                    out: dict[str, Any] = {
                        "ok": True,
                        "post_id": pid,
                        "to_id": to_id,
                        "kind": kind,
                        "commission_id": commission_id,
                        "commissioned": True,
                    }
                else:
                    pid = house_post.send(
                        conn,
                        from_id=owner_agent,
                        to_id=to_id,
                        body=body,
                        at=when,
                        kind=kind,
                        subject=subject,
                    )
                    out = {
                        "ok": True, "post_id": pid, "to_id": to_id, "kind": kind,
                    }
            # Project CoS↔peer posts into messenger-style room + DM chip.
            try:
                from soveryn.rooms import context as room_ctx

                dm = room_ctx.dm_session_id.get()
                room_sid = room_ctx.room_session_id.get()
                root = room_ctx.data_root.get()
                conv = None
                try:
                    from flask import current_app
                    conv = (current_app.extensions.get("soveryn") or {}).get("conv_store")
                except Exception:
                    conv = None
                if conv is not None and root:
                    ev = record_house_post_collab(
                        conv,
                        data_root=root,
                        from_id=owner_agent,
                        to_id=to_id,
                        body=body,
                        dm_session_id=dm,
                        room_session_id=room_sid,
                        commission_id=commission_id,
                    )
                    if ev:
                        out["room_event"] = ev
            except Exception:
                pass
            return out
        except Exception as exc:
            return {"ok": False, "error": repr(exc)}

    def list_posts(args: Mapping[str, Any]) -> dict[str, Any]:
        box = (args.get("box") or "inbox").strip()
        try:
            limit = int(args.get("limit") or 20)
        except (TypeError, ValueError):
            limit = 20
        try:
            with connect(_db()) as conn:
                rows = house_post.list_for(conn, owner_agent, box=box, limit=limit)
            return {"ok": True, "posts": rows, "count": len(rows)}
        except Exception as exc:
            return {"ok": False, "error": repr(exc)}

    registry.register(
        ToolSpec(
            name="house_post_send",
            owner=owner_agent,
            description=(
                "Message another citizen and put work on their commission queue "
                "when you are Aetheria. Commission peers: eve (research + posts), "
                "kernel (build). Vett and Scotty are parked — do not assign new "
                "work to them; use eve or kernel instead. When Jon says 'ask Eve "
                "to…' or 'have Kernel check…' — call this in the SAME turn with "
                "to_id set and a clear brief in body. Prefer kind=request "
                "(default). Kinds: memo, request, report, directive, ack."
            ),
            schema={
                "type": "object",
                "properties": {
                    "to_id": {"type": "string"},
                    "body": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "enum": ["memo", "request", "report", "directive", "ack"],
                    },
                    "subject": {"type": "string"},
                },
                "required": ["to_id", "body"],
            },
            handler=send,
        )
    )
    registry.register(
        ToolSpec(
            name="house_post_list",
            owner=owner_agent,
            description="List House Post messages for this citizen (inbox or outbox).",
            schema={
                "type": "object",
                "properties": {
                    "box": {"type": "string", "enum": ["inbox", "outbox", "all"]},
                    "limit": {"type": "integer"},
                },
            },
            handler=list_posts,
        )
    )
