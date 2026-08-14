"""Tools so agents can use House Post from inside AgentLoop."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from soveryn.citizens import post as house_post
from soveryn.citizens.registry import connect
from soveryn.platform.tools.registry import ToolRegistry, ToolSpec

_DEFAULT_DB = Path.home() / "soveryn_vnext" / "data" / "citizens.db"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _db() -> Path:
    import os
    return Path(os.environ.get("SOVERYN_CITIZENS_DB") or _DEFAULT_DB)


def register_house_post_tools(registry: ToolRegistry, *, owner_agent: str) -> None:
    def send(args: Mapping[str, Any]) -> dict[str, Any]:
        to_id = (args.get("to_id") or "").strip()
        body = (args.get("body") or "").strip()
        kind = (args.get("kind") or "memo").strip()
        subject = (args.get("subject") or "").strip() or None
        if not to_id or not body:
            return {"ok": False, "error": "to_id and body required"}
        try:
            with connect(_db()) as conn:
                pid = house_post.send(
                    conn,
                    from_id=owner_agent,
                    to_id=to_id,
                    body=body,
                    at=_now(),
                    kind=kind,
                    subject=subject,
                )
            return {"ok": True, "post_id": pid, "to_id": to_id, "kind": kind}
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
                "Send a House Post to another citizen (vett, scotty, aetheria). "
                "Kinds: memo, request, report, directive, ack. "
                "Use request/report with COS (aetheria) for routing; do not invent channels."
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
