"""AgentDispatcher — invokes a destination agent's AgentLoop with a
webhook-shaped prompt.

Each agent has a durable "webhook session" (one session id per agent,
recycled across events) so the audit trail of webhook-triggered activity
is isolated from the agent's user-facing chat history. Tool calls made
during the invocation propagate chain_depth via the thread-local set
by chain_context(), so emitted events inherit the chain metadata.
"""

from __future__ import annotations

import logging
from typing import Any

from soveryn.platform.coordination.events import (
    ChainContext,
    CoordEvent,
    CoordEventKind,
    chain_context,
)


logger = logging.getLogger(__name__)

WEBHOOK_SESSION_TITLE_PREFIX = "[webhook]"
WEBHOOK_AGENT_TAG = "webhook"


def build_webhook_prompt(event: CoordEvent) -> str:
    """Construct a tight, instructional prompt describing the event.

    NEEDS_DIRECTION events get a specific template that explicitly tells
    Aetheria HOW to respond (via direct_message_agent), since these
    events ARE requests for a structured action, not generic notifications.
    See docs/superpowers/specs/2026-06-05-direct-agent-communication-design.md.
    """
    if event.kind == CoordEventKind.NEEDS_DIRECTION:
        payload = event.payload or {}
        requester = payload.get("requester_agent") or event.actor_agent
        summary = payload.get("context_summary", "")
        options = payload.get("options_considered", []) or []
        options_block = (
            "\n".join(f"  - {opt}" for opt in options)
            if options else "  (no options listed)"
        )
        return (
            f"[NEEDS_DIRECTION at coord:{event.node_id}]\n"
            f"{requester} paused for your decision.\n\n"
            f"Context: {summary}\n\n"
            f"Options considered:\n{options_block}\n\n"
            f"Use direct_message_agent(target='{requester}', mode='execute', "
            f"coord_node_id='{event.node_id}', message='<your decision>') "
            f"to instruct them on which way to go.\n"
            f"Chain depth: {event.chain_depth}"
        )

    kind = event.kind.value
    lines = [
        f"[BOARD EVENT] {kind} on coord node {event.node_id}.",
        f"Actor: {event.actor_agent}",
    ]
    # Kind-specific context.
    payload = event.payload or {}
    if "board" in payload:
        lines.append(f"Board: {payload['board']}")
    if "old_status" in payload and "new_status" in payload:
        lines.append(f"Status: {payload['old_status']} -> {payload['new_status']}")
    if "target_board" in payload:
        lines.append(f"Promoted from {payload.get('source_board', '?')} -> "
                     f"{payload['target_board']}")
        if "source_node_id" in payload:
            lines.append(f"Source coord node: {payload['source_node_id']}")
    if "blocks_blueprint_id" in payload:
        lines.append(f"Blocks blueprint: {payload['blocks_blueprint_id']}")
    if "content_head" in payload:
        lines.append(f"Content preview: {payload['content_head']}")
    if "lesson_content_head" in payload:
        lines.append(f"Lesson learned: {payload['lesson_content_head']}")
    lines.append("")
    lines.append(
        "You were triggered because the routing rule for this event identified "
        "you as the responsible agent. Read the relevant coord node(s) via "
        "read_coordination_nodes if you need context, then take the appropriate "
        "action via your tools. If no action is warranted, respond briefly with "
        "why and the event will close out."
    )
    lines.append(f"Chain depth: {event.chain_depth}")
    return "\n".join(lines)


class AgentDispatcher:
    """Owns the AgentLoops dict and the conv_store. Maintains a webhook
    session per destination agent, lazily created on first use. Invokes
    AgentLoop.process_message inside a chain_context so tool-call emissions
    carry chain_depth + parent_event_id correctly."""

    def __init__(self, agent_loops: dict[str, Any], conv_store: Any) -> None:
        self.agent_loops = agent_loops
        self.conv_store = conv_store
        self._webhook_sessions: dict[str, str] = {}

    def _ensure_webhook_session(self, agent: str) -> str:
        sid = self._webhook_sessions.get(agent)
        if sid is not None:
            # Verify still exists in the conv store (the agent's session
            # could have been deleted by the user via the × button).
            if self.conv_store.get_session(sid) is not None:
                return sid
            # Stale handle; fall through to create a fresh one.
        title = f"{WEBHOOK_SESSION_TITLE_PREFIX} {agent}"
        sid = self.conv_store.new_session(agent, title=title)
        self._webhook_sessions[agent] = sid
        return sid

    def dispatch(self, event: CoordEvent, destination_agent: str) -> str | None:
        """Run the destination agent against the webhook prompt. Returns the
        agent's response content, or None if the agent has no AgentLoop
        registered. Errors during process_message propagate to the worker
        (which catches and logs them; one dispatch failure doesn't poison
        the queue).
        """
        loop = self.agent_loops.get(destination_agent)
        if loop is None:
            logger.warning(
                "no AgentLoop registered for destination agent %r; dropping event %s",
                destination_agent, event.id,
            )
            return None
        session_id = self._ensure_webhook_session(destination_agent)
        prompt = build_webhook_prompt(event)
        ctx = ChainContext(
            parent_event_id=event.id,
            chain_depth=event.chain_depth,
        )
        with chain_context(ctx):
            response = loop.process_message(session_id, prompt)
        # process_message returns a ChatResponse; we surface the content.
        return getattr(response, "content", None)
