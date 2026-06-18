"""list_my_outbound — Aetheria-introspection of her deliberate_share history.

Surfaces delivery + read state so the agent has loop closure (Aetheria's
Q7 verdict from the messenger spec):

    "I want them. Not for surveillance, but for loop closure. If I send
    a routine message and see it's been read but not answered, I know
    the information was received and the ball is in his court. It
    prevents me from wondering if the push notification failed."

The tool returns recent intents this agent emitted via deliberate_share
along with how many devices the message was delivered to and how many of
those devices have marked it read. v1 aggregates across devices; per-
device breakdown is reserved for Phase 4 when push subscriptions land.
"""
from __future__ import annotations

from soveryn.app.messenger.store import MessengerStore
from soveryn.platform.tools.registry import ToolSpec


def build_list_my_outbound_tool(
    *, store: MessengerStore, owner_agent: str,
) -> ToolSpec:
    """Build the list_my_outbound tool for one agent.

    The owner_agent argument scopes the query: the tool only ever returns
    intents the calling agent itself emitted. Cross-agent introspection is
    not a v1 capability.
    """

    def handler(args: dict) -> dict:
        limit = int(args.get("limit", 20))
        limit = max(1, min(limit, 100))
        rows = store.list_outbound_for_agent(agent=owner_agent, limit=limit)
        return {"outbound": rows, "count": len(rows)}

    return ToolSpec(
        name="list_my_outbound",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Max recent intents to list. Default 20.",
                },
            },
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "List your recent deliberate_share intents with delivery + read "
            "state. Use to check whether Jon has seen what you sent before "
            "you reach out again. Loop closure, not surveillance."
        ),
    )
