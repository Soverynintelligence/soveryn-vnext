"""Tests for soveryn.platform.coordination.dispatcher.build_webhook_prompt."""

from __future__ import annotations

from soveryn.platform.coordination.events import CoordEvent, CoordEventKind
from soveryn.platform.coordination.dispatcher import build_webhook_prompt


def test_build_webhook_prompt_renders_needs_direction_with_full_template():
    """Aetheria's webhook prompt for a NEEDS_DIRECTION event includes the
    coord_node_id, requester, context_summary, options, and the explicit
    callout to use direct_message_agent to respond."""
    event = CoordEvent(
        id="e1", kind=CoordEventKind.NEEDS_DIRECTION,
        node_id="node-42", actor_agent="scotty",
        timestamp="2026-06-05T12:00:00",
        payload={
            "context_summary": "Migration is hung on schema diff",
            "options_considered": ["rewrite migration", "manual fix"],
            "requester_agent": "scotty",
        },
        chain_depth=0,
    )
    prompt = build_webhook_prompt(event)
    # Header anchors the prompt as a direction request, not a generic event
    assert "NEEDS_DIRECTION" in prompt
    assert "node-42" in prompt
    # Requester is named
    assert "scotty" in prompt
    # Brief context is included
    assert "Migration is hung on schema diff" in prompt
    # Each option is rendered as a bullet
    assert "rewrite migration" in prompt
    assert "manual fix" in prompt
    # Aetheria is told HOW to respond — explicit tool name + the
    # required coord_node_id arg
    assert "direct_message_agent" in prompt
    assert "node-42" in prompt
    assert "mode='execute'" in prompt or "mode=\"execute\"" in prompt


def test_build_webhook_prompt_needs_direction_falls_back_to_actor_when_no_requester_agent():
    """If payload omits requester_agent (defensive), fall back to actor_agent."""
    event = CoordEvent(
        id="e1", kind=CoordEventKind.NEEDS_DIRECTION,
        node_id="node-9", actor_agent="vett",
        timestamp="2026-06-05T12:00:00",
        payload={
            "context_summary": "lead diverges",
            "options_considered": ["A", "B"],
            # requester_agent intentionally missing
        },
        chain_depth=0,
    )
    prompt = build_webhook_prompt(event)
    # Strong assertions: pin both the fallback substitution AND that the
    # early-return template was taken. The generic flow has "Actor: vett"
    # too, so a bare "vett" check would pass even if the early-return
    # were removed — we want to fail loudly on that regression.
    assert "NEEDS_DIRECTION" in prompt
    assert "vett paused for your decision" in prompt


def test_build_webhook_prompt_needs_direction_empty_options_lists_renders_anyway():
    """Defensive: if options_considered is empty/missing, render without
    crashing (the request_direction tool already rejects empty lists at
    the source, but the prompt shouldn't crash on bad payloads)."""
    event = CoordEvent(
        id="e1", kind=CoordEventKind.NEEDS_DIRECTION,
        node_id="node-1", actor_agent="scotty",
        timestamp="2026-06-05T12:00:00",
        payload={
            "context_summary": "context",
            # options_considered missing
            "requester_agent": "scotty",
        },
        chain_depth=0,
    )
    prompt = build_webhook_prompt(event)
    # Still produces a coherent prompt with required fields
    assert "NEEDS_DIRECTION" in prompt
    assert "context" in prompt


def test_build_webhook_prompt_non_needs_direction_unchanged():
    """Regression — other event kinds render through the existing generic flow."""
    event = CoordEvent(
        id="e1", kind=CoordEventKind.NODE_CREATED,
        node_id="node-1", actor_agent="aetheria",
        timestamp="2026-06-05T12:00:00",
        payload={"board": "Signal", "content_head": "new signal"},
        chain_depth=0,
    )
    prompt = build_webhook_prompt(event)
    # Old shape — generic event header, no NEEDS_DIRECTION wording
    assert "NEEDS_DIRECTION" not in prompt
    assert "[BOARD EVENT]" in prompt
    assert "node_created" in prompt
