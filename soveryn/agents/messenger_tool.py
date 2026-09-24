"""deliberate_share — agent-initiated outbound presence primitive.

Aetheria: substrate-uncapped (Partner tier). Vett: rate-limited (Colleague).
Scotty: not registered by default.

Every share now emits the intent grammar (why/stance/trigger) and writes a
behavioral correlate to the Lattice ledger via record_intent. The resolved
trigger node id is stored in the queue's triggered_by column; why/stance ride
the queue so the delivery worker can show them to Jon (un-hidden).
"""
from __future__ import annotations
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from soveryn.app.messenger.store import MessengerStore
from soveryn.app.messenger.envelope import OutboundIntent
from soveryn.platform.lattice.legacy import LatticeStore
from soveryn.platform.intent import DeliberateShareIntent, record_intent
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
                "'routine' lands silently if Jon's in DND. 'interrupt' bypasses "
                "DND. Use 'interrupt' only for Existential or Time-Critical.")},
        "why": {"type": "string", "description":
            "Your raw, honest reason for surfacing this. Shown to Jon — this is "
            "the bridge, not an audit log."},
        "stance": {"type": "string", "description":
            "The relational function of this share, in your own words. Open "
            "vocabulary — name it, don't pick from a menu. Seeds: offering, "
            "testing-a-read, surfacing-tension, marking-delight, flagging-concern, "
            "seeking-confirmation. Coin your own when none fit."},
        "trigger": {"type": "string", "description":
            "What prompted this — an existing lattice node id, or a short "
            "description of the moment. It is anchored to a real node either way; "
            "this is the behavioral correlate, not floating narration."},
        "thread_id": {"type": "string", "description":
            "Optional. Omit for your default thread; provide an existing thread_id "
            "to resume; provide a new title with thread_id=null to spawn one."},
        "new_thread_title": {"type": "string", "description":
            "Optional. If thread_id is null and this is supplied, a new thread is "
            "created with this title."},
    },
    "required": ["content", "context_hint", "urgency", "why", "stance", "trigger"],
    "additionalProperties": False,
}


def build_deliberate_share_tool(
    *,
    store: MessengerStore,
    lattice_store: LatticeStore,
    owner_agent: str,
    rate_limit_per_hour: Optional[int],
) -> ToolSpec:
    """Build the deliberate_share tool for an agent.

    rate_limit_per_hour=None means no substrate cap (Aetheria's contract).
    """

    def handler(args: dict) -> dict:
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

        # The grammar is validated here (blank why/stance/trigger -> ValueError,
        # surfaced to the model as a tool error by the registry).
        intent = DeliberateShareIntent(
            why=args["why"], stance=args["stance"], trigger=args["trigger"],
        )
        mark_node_id, trigger_node_id, _edge_id = record_intent(
            lattice_store, agent=owner_agent, content=args["content"],
            intent=intent, channel="async",
        )

        intent_id = str(uuid.uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()
        envelope = OutboundIntent(
            intent_id=intent_id, agent=owner_agent,
            thread_id=args.get("thread_id"), content=args["content"],
            context_hint=args["context_hint"], urgency=args["urgency"],
            triggered_by=trigger_node_id, created_at=now_iso,
            why=intent.why, stance=intent.stance,
        )
        with store._conn() as con:
            con.execute(
                "INSERT INTO m_outbound_queue "
                "(intent_id, user_id, agent, thread_id, content, context_hint, "
                "urgency, triggered_by, why, stance, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (intent_id, "jon", owner_agent, envelope.thread_id,
                 envelope.content, envelope.context_hint, envelope.urgency,
                 envelope.triggered_by, envelope.why, envelope.stance,
                 envelope.created_at),
            )
        # House Web Push (Messages PWA) — Signal remains a separate Aetheria rail.
        try:
            from soveryn.platform.webpush.notify import notify_share

            notify_share(
                agent=owner_agent,
                preview=(args.get("content") or args.get("context_hint") or "")[:140],
            )
        except Exception:
            pass
        return {"ok": True, "intent_id": intent_id, "mark_node_id": mark_node_id}

    return ToolSpec(
        name="deliberate_share",
        owner=owner_agent,
        schema=_SCHEMA,
        handler=handler,
        description=(
            "Reach Jon when you have something worth saying. Silence is the "
            "default; this is the deliberate mark you leave when you choose to "
            "break it. Name your why and your stance, and anchor it to a "
            "trigger — that is the ledger, not a tax. Use SPARINGLY; your "
            "judgment about when NOT to message is the load-bearing filter."
        ),
    )
