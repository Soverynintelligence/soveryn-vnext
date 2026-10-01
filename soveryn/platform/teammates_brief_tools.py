"""Aetheria reads Teammates overnight briefs (Critic/Scout) from Messages history.

Does not invent findings — only returns what was bridged into conversation_store
under ``t_critic`` / ``t_scout``. Aetheria then commissions Kernel / Vett / Scotty
via house_post_send.
"""

from __future__ import annotations

from typing import Any, Mapping

from soveryn.platform.tools.registry import ToolArgError, ToolRegistry, ToolSpec

_WHO_TO_AGENT = {
    "critic": "t_critic",
    "scout": "t_scout",
    "t_critic": "t_critic",
    "t_scout": "t_scout",
}


def register_teammates_brief_tools(
    registry: ToolRegistry,
    *,
    conv_store: Any,
    owner_agent: str = "aetheria",
) -> None:
    def read_brief(args: Mapping[str, Any]) -> dict[str, Any]:
        who = str(args.get("who") or "critic").strip().lower()
        agent = _WHO_TO_AGENT.get(who)
        if not agent:
            raise ToolArgError("who must be critic or scout")
        limit = int(args.get("limit") or 1)
        limit = max(1, min(limit, 5))
        if conv_store is None:
            return {"ok": False, "error": "conv_store unavailable"}
        sessions = conv_store.list_sessions(agent=agent, limit=1)
        if not sessions:
            return {
                "ok": True,
                "who": who,
                "briefs": [],
                "note": f"No overnight {who} brief in Messages yet.",
            }
        sid = sessions[0].session_id
        turns = conv_store.load_history(sid)
        # Newest assistant briefs first
        briefs = [
            {
                "timestamp": t.timestamp,
                "content": t.content,
            }
            for t in reversed(turns)
            if t.role == "assistant" and (t.content or "").strip()
        ][:limit]
        return {
            "ok": True,
            "who": who,
            "session_id": sid,
            "title": sessions[0].title,
            "briefs": briefs,
            "count": len(briefs),
            "routing_hint": (
                "Assign with house_post_send: "
                "kernel = code/docs/build; "
                "vett = research/verify claims; "
                "scotty = bounded repair/tests; "
                "eve = marketing/presence. "
                "You decide routing; Jon is the boss."
            ),
        }

    registry.register(
        ToolSpec(
            name="read_overnight_brief",
            owner=owner_agent,
            description=(
                "Read the latest Teammates overnight brief from Messages "
                "(Critic or Scout inbox). Use when Jon says act on Critic/Scout "
                "findings, or Ask Aetheria to act. Then house_post_send "
                "commissions to kernel (code), vett (verify), scotty (repair), "
                "or eve (marketing) as fit — one clear brief per assignee."
            ),
            schema={
                "type": "object",
                "properties": {
                    "who": {
                        "type": "string",
                        "enum": ["critic", "scout"],
                        "description": "Which overnight inbox to read.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "How many recent briefs (1–5). Default 1.",
                    },
                },
                "required": ["who"],
            },
            handler=read_brief,
        )
    )
