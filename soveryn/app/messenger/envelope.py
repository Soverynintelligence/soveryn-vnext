"""Wire-format envelopes for messenger I/O.

These dataclasses lock the message shape spec §6 defines. Any change here
needs to be reflected in Codex's PWA client and the active-context
manager's event payloads — see the cross-rail spec §11.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, Optional


Urgency = Literal["routine", "interrupt"]
_VALID_URGENCIES = frozenset({"routine", "interrupt"})


@dataclass(frozen=True)
class InboundMessage:
    """Jon → agent, parsed from POST /m/threads/<tid>/send_stream."""
    client_msg_id: str
    thread_id: str
    agent: str
    content: str
    attachments: tuple[dict, ...]
    device_id: str
    client_ts: str


@dataclass(frozen=True)
class OutboundIntent:
    """Agent → Jon via deliberate_share, queued for the delivery worker."""
    intent_id: str
    agent: str
    thread_id: Optional[str]   # None = default thread for this agent
    content: str
    context_hint: str          # short push-preview, <=100 chars
    urgency: str
    triggered_by: str          # resolved trigger node id (ledger anchor)
    created_at: str
    why: str = ""              # honest reason — shown to Jon
    stance: str = ""           # relational function (open vocabulary) — shown to Jon

    def __post_init__(self) -> None:
        if self.urgency not in _VALID_URGENCIES:
            raise ValueError(
                f"urgency must be one of {sorted(_VALID_URGENCIES)}, "
                f"got {self.urgency!r}"
            )
        if len(self.context_hint) > 100:
            raise ValueError(
                f"context_hint must be <=100 chars; got {len(self.context_hint)}"
            )


@dataclass(frozen=True)
class ThreadListEntry:
    """One row in GET /m/threads."""
    thread_id: str
    agent: str
    title: str
    last_message_preview: str
    last_message_at: str
    last_message_by: Literal["user", "agent"]
    unread_count: int
    muted: bool


@dataclass(frozen=True)
class MessageEnvelope:
    """One row in GET /m/threads/<tid>/messages.

    v1 keeps content as str; vision parts list deferred (see spec §6).
    """
    message_id: str
    thread_id: str
    by: Literal["user", "agent"]
    agent: str
    content: str
    client_msg_id: Optional[str]   # only set for user messages
    created_at: str
    delivered_at: Optional[str]
    read_at: Optional[str]
    tool_calls: Optional[tuple[dict, ...]]
    finish_reason: Optional[str]
    context_hint: Optional[str]    # agent-initiated only
    urgency: Optional[str]
