"""Latest timestamp-filtered, all-agent evidence with stable premise IDs."""
from __future__ import annotations

from datetime import datetime
import logging

from soveryn.agents.representation.prompt import render_representation_prompt
from soveryn.agents.representation.sources import (
    EvidenceTurn, is_autonomous_title, recent_turns,
)

logger = logging.getLogger(__name__)
# Conservative UTF-8 byte ceiling, not a chars/4 token guess. Even one token
# per byte leaves >4K tokens for chat framing + 1K generation inside 16K.
MAX_PROMPT_BYTES = 10_000
_is_autonomous = is_autonomous_title


def _clip(text: str, limit: int) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    return raw[:max(0, limit - 3)].decode("utf-8", errors="ignore") + "..."


def _speaker(turn: EvidenceTurn, *, owner_agent: str, subject: str) -> str:
    if turn.role == "assistant":
        return turn.agent[:1].upper() + turn.agent[1:]
    if turn.agent == owner_agent:
        return subject[:1].upper() + subject[1:]
    return f"Unverified user on {turn.agent} (NOT established as {subject})"


def build_briefing(conv_store, lattice_store, *, owner_agent: str,
                   subject: str, turns_per_briefing: int,
                   now: datetime | None = None,
                   turns: list[EvidenceTurn] | None = None,
                   ) -> tuple[str, str, list[str]]:
    now = now or datetime.now()
    turns = recent_turns(conv_store, now=now) if turns is None else turns
    selected = turns[-turns_per_briefing:] if turns_per_briefing > 0 else []
    lines = [(t.id, f"[node:{t.id}] {_speaker(t, owner_agent=owner_agent, subject=subject)}: "
                    f"{_clip(t.content, 1800)}") for t in selected]
    prior = []
    for node in lattice_store.iter_nodes(agent=owner_agent, include_library=False):
        if node.type == "conclusion" and (node.provenance or {}).get("subject") == subject:
            prior.append((node.id, f"[node:{node.id}] {_clip(node.content, 1000)}"))

    def rendered_size():
        return len(render_representation_prompt(
            subject=subject, briefing="\n".join(s for _, s in lines),
            prior_conclusions="\n".join(s for _, s in prior)).encode("utf-8"))

    # Keep newest evidence first; prior history cannot crowd it out.
    while rendered_size() > MAX_PROMPT_BYTES and prior:
        prior.pop(0)
    while rendered_size() > MAX_PROMPT_BYTES and len(lines) > 2:
        lines.pop(0)
    while rendered_size() > MAX_PROMPT_BYTES and lines:
        # IDs and speaker labels remain intact; only evidence text is clipped.
        shortened = []
        for nid, line in lines:
            prefix, body = line.split(": ", 1)
            shortened.append((nid, prefix + ": " + _clip(body, max(16, len(body.encode("utf-8")) // 2))))
        if shortened == lines:
            raise ValueError("representation prompt template exceeds safe byte budget")
        lines = shortened
    if rendered_size() > MAX_PROMPT_BYTES:
        raise ValueError("representation prompt template exceeds safe byte budget")
    return ("\n".join(s for _, s in lines), "\n".join(s for _, s in prior),
            [nid for nid, _ in lines + prior])
