"""Delivery for automations.

Dry-run: ``preview_delivery`` renders the message + destination a live run
WOULD use, with no side effects. Used whenever an automation is dry-run-only.

Live: ``deliver_live`` drives the spec's citizen through one real
``AgentLoop.process_message`` turn IN-PROCESS. The citizen's tools fire
normally; the Approval Gate (wired on the loop) blocks any gated egress until
a human approves it in the Command Center. ``deliver_live`` is only ever
called from within the running Flask app, where the loops + conv store live on
``app.extensions['soveryn']`` — see ``api_automations.api_automations_run``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence

from .prefs import resolve_channels
from .registry import AutomationSpec

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..agents.loop import AgentLoop
    from ..memory.conversation_store import ConversationStore

logger = logging.getLogger("soveryn.automations.deliver")


@dataclass(frozen=True)
class DeliveryPreview:
    """What *would* be delivered, for a dry-run automation."""

    channels: tuple[str, ...]
    target: str
    body: str

    @property
    def channel(self) -> str:
        """Primary channel (first effective) for back-compat."""
        return self.channels[0] if self.channels else "command_center"


def preview_delivery(
    spec: AutomationSpec,
    *,
    channels: Optional[Sequence[str]] = None,
    prompt: Optional[str] = None,
) -> DeliveryPreview:
    """Build a delivery preview without sending anything."""
    effective: List[str]
    if channels is None:
        effective = resolve_channels(spec.id)
    else:
        effective = [str(c) for c in channels]
    if not effective:
        effective = ["command_center"]
    chan_list = ", ".join(effective)
    body_prompt = prompt if prompt is not None else spec.prompt
    body = (
        f"[dry-run] {spec.title} ({spec.id})\n"
        f"agent: {spec.agent}\n"
        f"channels: {chan_list}\n"
        f"prompt: {body_prompt}"
    )
    return DeliveryPreview(
        channels=tuple(effective),
        target=spec.delivery.target,
        body=body,
    )


def _automation_session_title(spec: AutomationSpec) -> str:
    """Deterministic session title so a re-run resumes the same conversation."""
    return f"automation:{spec.id}"


def _find_or_create_session(
    conv_store: "ConversationStore",
    agent: str,
    title: str,
) -> str:
    """Return the session_id for an existing ``title``-matched session for
    ``agent``, or mint a fresh one if none exists.

    Reusing the session keeps a duty's running context across firings (the
    citizen remembers its prior work for that duty). Scoped to the agent so a
    same-named title on a different citizen never collides.
    """
    for session in conv_store.list_sessions(agent=agent, limit=200):
        if session.title == title:
            return session.session_id
    return conv_store.new_session(agent, title=title)


def deliver_live(
    spec: AutomationSpec,
    agent_loop: "AgentLoop",
    conv_store: "ConversationStore",
    *,
    channels: Optional[Sequence[str]] = None,
    prompt: Optional[str] = None,
) -> Dict[str, object]:
    """Run one live turn of ``spec`` through ``agent_loop`` in-process.

    Find-or-creates a persistent session titled ``automation:<id>`` for
    ``spec.agent`` and drives a single ``process_message`` turn with
    ``spec.prompt`` (source="automation"). The gate governs any egressing tool
    the citizen calls — ungated tools (e.g. signal_send) fire, gated tools
    (e.g. x_post, email_send) are held for human approval.

    Returns a dict mirroring the ``POST /chat`` JSON shape so the UI can render
    a live run exactly like a chat turn, plus the declared delivery envelope:

        {
          "status": "ok",
          "mode": "live",
          "dry_run": False,
          "agent": str,
          "session_id": str,
          "content": str,
          "finish_reason": str,
          "tool_calls": list[dict] | None,
          "usage": dict | None,
          "context_usage": dict | None,
          "channel": str,
          "channels": list[str],
          "target": str,
        }

    Raises:
        AgentLoopError — session/agent mismatch or a rejected attachment.
        LlamaServerError / LlamaServerTimeout — the local model server failed.
    """
    effective: List[str]
    if channels is None:
        effective = resolve_channels(spec.id)
    else:
        effective = [str(c) for c in channels]
    if not effective:
        effective = ["command_center"]

    session_id = _find_or_create_session(
        conv_store, spec.agent, _automation_session_title(spec)
    )
    turn_prompt = prompt if prompt is not None else spec.prompt
    token = None
    try:
        from .notepad_tool import current_automation_id

        token = current_automation_id.set(spec.id)
    except Exception:  # pragma: no cover — tool module optional at import
        token = None
    try:
        response = agent_loop.process_message(
            session_id, turn_prompt, source="automation"
        )
    finally:
        if token is not None:
            from .notepad_tool import current_automation_id

            current_automation_id.reset(token)
    logger.info(
        "live delivery: %s (agent=%s, session=%s, finish=%s)",
        spec.id,
        spec.agent,
        session_id,
        response.finish_reason,
    )
    return {
        "status": "ok",
        "mode": "live",
        "dry_run": False,
        "agent": spec.agent,
        "session_id": session_id,
        "content": response.content,
        "finish_reason": response.finish_reason,
        "tool_calls": list(response.tool_calls) if response.tool_calls else None,
        "usage": response.usage,
        "context_usage": response.context_usage,
        "channel": effective[0],
        "channels": effective,
        "target": spec.delivery.target,
    }


def deliver(
    spec: AutomationSpec,
    *,
    dry_run: bool = True,
    channels: Optional[Sequence[str]] = None,
    agent_loop: Optional["AgentLoop"] = None,
    conv_store: Optional["ConversationStore"] = None,
    prompt: Optional[str] = None,
) -> Dict[str, object]:
    """Deliver (or preview, in dry-run) an automation's output.

    dry_run=True  -> ``preview_delivery`` only; nothing is sent.
    dry_run=False -> ``deliver_live``; requires ``agent_loop`` + ``conv_store``
                     (the in-process loops from the running app). Refuses with
                     a clear error if either is missing, so a caller that
                     forgot the live context can never silently no-op.
    """
    preview = preview_delivery(spec, channels=channels, prompt=prompt)
    if not dry_run:
        if agent_loop is None or conv_store is None:
            logger.error(
                "live delivery refused: no in-process agent_loop/conv_store "
                "provided for %s",
                spec.id,
            )
            return {
                "status": "refused",
                "mode": "live",
                "dry_run": False,
                "channel": preview.channel,
                "channels": list(preview.channels),
                "target": preview.target,
                "message": (
                    "live delivery needs the running app's in-process agent "
                    "loop + conversation store; none were provided"
                ),
            }
        return deliver_live(
            spec, agent_loop, conv_store, channels=channels, prompt=prompt
        )

    logger.info(
        "dry-run delivery: %s -> %s (%s)",
        spec.id,
        list(preview.channels),
        preview.target,
    )
    return {
        "status": "would_send",
        "mode": "dry_run",
        "dry_run": True,
        "channel": preview.channel,
        "channels": list(preview.channels),
        "target": preview.target,
        "preview": preview.body,
    }
