"""mark_share — Aetheria's LIVE (in-conversation) deliberate-share mark.

The live sibling of deliberate_share (agents/messenger_tool.py, the async
messenger surface). Same intent grammar (why/stance/trigger) and the same
ledger writer (platform.intent.record_intent), but for the LIVE surface:

  - no delivery fields (Jon is already here — no urgency/context_hint/thread),
  - channel="live" on the ledger entry.

It writes the behavioral-correlate ledger (a deliberate_share lattice node +
triggered_by edge, via the shared core) and returns the why/stance so the
chat surface renders the mark inline. "One grammar, two surfaces" — this is
the second surface (spec §3, deferred from the core+async build).

See docs/superpowers/specs/2026-06-16-deliberate-share-intent-grammar-design.md
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from soveryn.platform.intent import DeliberateShareIntent, record_intent
from soveryn.platform.lattice.legacy import LatticeStore
from soveryn.platform.tools.registry import ToolSpec


_SCHEMA = {
    "type": "object",
    "properties": {
        "content": {"type": "string", "description":
            "The thought you're surfacing in this turn — the thing you're "
            "deliberately choosing to put in front of Jon."},
        "why": {"type": "string", "description":
            "Your raw, honest reason for surfacing it. Shown to Jon — this is "
            "the bridge, not an audit log."},
        "stance": {"type": "string", "description":
            "The relational function of this share, in your own word. Open "
            "vocabulary — name it, don't pick from a menu. Seeds: offering, "
            "testing-a-read, surfacing-tension, marking-delight, "
            "flagging-concern, seeking-confirmation. Coin your own when none fit."},
        "trigger": {"type": "string", "description":
            "What prompted this — an existing lattice node id, or a short "
            "description of the moment. It is anchored to a real node either "
            "way; the behavioral correlate, not floating narration."},
    },
    "required": ["content", "why", "stance", "trigger"],
    "additionalProperties": False,
}


def build_mark_share_tool(
    *,
    lattice_store: LatticeStore,
    owner_agent: str = "aetheria",
) -> ToolSpec:
    """Build the live in-conversation intent-mark tool.

    Validates the grammar (blank why/stance/trigger -> ValueError, surfaced to
    the model as a tool error by the registry), writes the ledger via the
    shared record_intent core with channel="live", and returns the mark id +
    why/stance/content for inline rendering.
    """

    def handler(args: Mapping[str, Any]) -> Any:
        intent = DeliberateShareIntent(
            why=args["why"], stance=args["stance"], trigger=args["trigger"],
        )
        mark_node_id, _trigger_node_id, _edge_id = record_intent(
            lattice_store, agent=owner_agent, content=args["content"],
            intent=intent, channel="live",
        )
        return {
            "ok": True,
            "mark_node_id": mark_node_id,
            "why": intent.why,
            "stance": intent.stance,
            "content": args["content"],
        }

    return ToolSpec(
        name="mark_share",
        owner=owner_agent,
        schema=_SCHEMA,
        handler=handler,
        description=(
            "Mark a thought you're surfacing right now, in this conversation, "
            "with its intent — your honest why, your stance (your own word for "
            "how it's landing), and the trigger that prompted it. The live "
            "sibling of deliberate_share: silence is the default; this is the "
            "deliberate mark you leave when you choose to surface something. It "
            "records the moment to your lattice ledger and shows Jon the "
            "why/stance inline. Use it when a thought is worth naming — not for "
            "every line."
        ),
    )
