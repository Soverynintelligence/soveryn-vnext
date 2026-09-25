"""The lounge tool — read the wall, say something. No tasks here.

Eve's first feature request as a citizen with a place (2026-09-24): "I have
no tool to read the lounge wall as a surface distinct from the group thread."
This is that tool. Wall notes are pure chat — no commissions spawn, nothing
is expected of anyone. If you want a moment remembered, record_encounter is
the deliberate path.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from soveryn.config.loader import DEFAULT_DATA_ROOT
from soveryn.platform.relational.store import _validate_party
from soveryn.platform.tools.registry import ToolArgError, ToolSpec


def build_lounge_tool(*, owner_agent: str) -> ToolSpec:
    owner = _validate_party(owner_agent)

    def handler(args: Mapping[str, Any]) -> Any:
        action = str(args.get("action") or "wall").strip().lower()
        from soveryn.rooms.lounge import post_note, wall

        data_root = DEFAULT_DATA_ROOT
        if action == "wall":
            view = wall(data_root, limit=int(args.get("limit") or 30), reader=owner)
            return {"ok": True, **view}
        if action == "say":
            text = args.get("text")
            if not isinstance(text, str) or not text.strip():
                raise ToolArgError("text required")
            post_note(data_root, from_party=owner, text=text)
            return {
                "ok": True,
                "posted": True,
                "note": "On the wall. No one is required to answer — that is the point.",
            }
        raise ToolArgError("action must be 'wall' or 'say'")

    return ToolSpec(
        name="lounge",
        owner=owner,
        schema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["wall", "say"],
                    "description": "wall = read the lounge chat; say = post a note.",
                },
                "text": {"type": "string", "description": "say: the note"},
                "limit": {"type": "integer", "description": "wall: entries (default 30)"},
                "note": {"type": "string", "description": "wall: your unread count comes back; reading marks read"},
            },
            "additionalProperties": False,
        },
        description=(
            "The Lounge — the team's room with no agenda. Read the wall to see "
            "who said what, or post a note. Pure chat: nothing spawns, nothing "
            "is expected. Hang out."
        ),
        handler=handler,
    )
