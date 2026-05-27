"""Durable event bus boundary for inter-agent communication.

The implementation is a cursor-based pub/sub interface with both an in-memory
fake and a SQLite-WAL event log. Agents publish and subscribe to events instead
of sharing in-process state.
"""

from soveryn.platform.bus.events import BusError, Event, EventType, KNOWN_EVENT_TYPES
from soveryn.platform.bus.memory import InMemoryBus
from soveryn.platform.bus.sqlite import SQLiteBus

__all__ = [
    "BusError",
    "Event",
    "EventType",
    "InMemoryBus",
    "KNOWN_EVENT_TYPES",
    "SQLiteBus",
]
