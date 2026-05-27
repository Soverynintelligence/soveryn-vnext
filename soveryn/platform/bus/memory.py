"""In-memory platform bus for unit tests and local fakes."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from soveryn.platform.bus.events import Event, EventType, validate_event_type


class InMemoryBus:
    """Simple cursor-based pub/sub with process-local durability only."""

    def __init__(self) -> None:
        self._events: list[Event] = []
        self._next_id = 1

    def publish(self, event_type: EventType, payload: dict[str, Any], actor: str) -> Event:
        checked_type = validate_event_type(event_type)
        event = Event(
            id=self._next_id,
            event_type=checked_type,
            payload=dict(payload),
            actor=actor,
        )
        self._events.append(event)
        self._next_id += 1
        return event

    def subscribe(
        self,
        event_types: Iterable[EventType],
        cursor: int = 0,
        *,
        limit: int | None = None,
    ) -> tuple[Event, ...]:
        wanted = {validate_event_type(event_type) for event_type in event_types}
        events = [
            event for event in self._events
            if event.id > cursor and event.event_type in wanted
        ]
        if limit is not None:
            events = events[:limit]
        return tuple(events)
