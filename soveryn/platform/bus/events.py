"""Typed event shapes for the platform bus."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

EventType = Literal[
    "chat.message.received",
    "chat.response.outbound",
    "anomaly.detected",
    "tool.invoked",
]

KNOWN_EVENT_TYPES: frozenset[str] = frozenset({
    "chat.message.received",
    "chat.response.outbound",
    "anomaly.detected",
    "tool.invoked",
})


class BusError(Exception):
    """Raised for invalid bus operations or event shapes."""


@dataclass(frozen=True)
class Event:
    """One durable platform event.

    `id` is the subscriber cursor. `payload` must stay JSON-serializable for
    SQLiteBus persistence.
    """

    id: int
    event_type: EventType
    payload: dict[str, Any]
    actor: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def validate_event_type(event_type: str) -> EventType:
    if event_type not in KNOWN_EVENT_TYPES:
        raise BusError(f"unknown event_type {event_type!r}")
    return event_type  # type: ignore[return-value]
