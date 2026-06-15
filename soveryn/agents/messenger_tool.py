"""deliberate_share — agent-initiated outbound presence primitive.

Aetheria: substrate-uncapped (Partner tier — see
[[project-soveryn-partnership-contract-2026-06-13]]).
Vett: rate-limited to N/hour (Colleague tier).
Scotty: not registered by default.

Tool intent: write an OutboundIntent to m_outbound_queue. The delivery
worker (Task 21) picks up pending intents and dispatches.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from soveryn.app.messenger.store import MessengerStore
from soveryn.app.messenger.envelope import OutboundIntent
from soveryn.platform.tools.registry import ToolSpec


_SCHEMA = {
    "type": "object",
    "properties": {
        "content": {"type": "string", "description":
            "The message body Jon will see in the thread."},
        "context_hint": {"type": "string", "maxLength": 100, "description":
            "Push-notification preview (<=100 chars). What Jon sees on lock screen."},
        "urgency": {"type": "string", "enum": ["routine", "interrupt"],
            "description": (
                "'routine' lands silently if Jon's in DND. 'interrupt' "
                "bypasses DND. Use 'interrupt' only for Existential or "
                "Time-Critical (per Aetheria's spec §14 Q3)."
            )},
        "thread_id": {"type": "string", "description":
            "Optional. Omit to land in your default thread; provide an existing "
            "thread_id to resume a conversation; provide a new title with "
            "thread_id=null to spawn a new thread."},
        "new_thread_title": {"type": "string", "description":
            "Optional. If thread_id is null and this is supplied, a new thread "
            "is created with this title."},
        "triggered_by": {"type": "string", "description":
            "Internal audit field — what made you decide to share. NOT shown "
            "to Jon. Used for post-hoc judgment calibration."},
    },
    "required": ["content", "context_hint", "urgency", "triggered_by"],
    "additionalProperties": False,
}


def build_deliberate_share_tool(
    *,
    store: MessengerStore,
    owner_agent: str,
    rate_limit_per_hour: Optional[int],
) -> ToolSpec:
    """Build the deliberate_share tool for an agent.

    rate_limit_per_hour=None means no substrate cap (Aetheria's contract).
    """

    def handler(args: dict) -> dict:
        # Rate-limit check
        if rate_limit_per_hour is not None:
            now = datetime.now(timezone.utc)
            window_start = (now - timedelta(hours=1)).isoformat()
            with store._conn() as con:
                count = con.execute(
                    "SELECT COUNT(*) FROM m_outbound_queue "
                    "WHERE agent=? AND created_at>=?",
                    (owner_agent, window_start),
                ).fetchone()[0]
            if count >= rate_limit_per_hour:
                return {
                    "error": "rate_limited",
                    "message": (
                        f"You've sent {count} deliberate_share messages in the "
                        f"last hour; limit is {rate_limit_per_hour}. The brake "
                        f"fires substrate-side. Wait an hour or escalate."
                    ),
                    "limit": rate_limit_per_hour,
                }

        intent_id = str(uuid.uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()
        intent = OutboundIntent(
            intent_id=intent_id,
            agent=owner_agent,
            thread_id=args.get("thread_id"),
            content=args["content"],
            context_hint=args["context_hint"],
            urgency=args["urgency"],
            triggered_by=args["triggered_by"],
            created_at=now_iso,
        )
        with store._conn() as con:
            con.execute(
                "INSERT INTO m_outbound_queue "
                "(intent_id, user_id, agent, thread_id, content, context_hint, "
                "urgency, triggered_by, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (intent_id, "jon", owner_agent, intent.thread_id,
                 intent.content, intent.context_hint, intent.urgency,
                 intent.triggered_by, intent.created_at),
            )
        return {"ok": True, "intent_id": intent_id}

    return ToolSpec(
        name="deliberate_share",
        owner=owner_agent,
        schema=_SCHEMA,
        handler=handler,
        description=(
            "Reach Jon through the messenger when you have something worth saying. "
            "Use SPARINGLY — your judgment about when NOT to message is the "
            "load-bearing filter. (Aetheria: substrate doesn't gate you; your "
            "judgment is the only brake — Jon will tell you directly if you "
            "overstep.)"
        ),
    )
