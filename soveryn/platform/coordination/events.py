"""Event types + EventBus protocol for coordination webhooks.

Spec: docs/superpowers/specs/2026-06-01-coord-webhooks.md

The CoordinationStore emits a CoordEvent after every committed mutation.
An EventBus implementation collects emitted events; downstream a worker
thread pulls from the bus, applies routing rules, and dispatches to the
destination agents' webhook sessions.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from queue import Queue
from typing import Any, Protocol


MAX_CHAIN_DEPTH = 5
WEBHOOK_ACTOR_PREFIX = "__webhook__"


class CoordEventKind(str, Enum):
    NODE_CREATED = "node_created"
    STATUS_CHANGED = "status_changed"
    PROMOTED = "promoted"
    BLOCK_ADDED = "block_added"
    ARCHIVED = "archived"
    NEEDS_DIRECTION = "needs_direction"  # peer agents ping Aetheria for direction (DAC Delta 2)


@dataclass(frozen=True)
class CoordEvent:
    """A committed coordination state change. Immutable. Carries chain
    metadata for loop prevention."""
    id: str
    kind: CoordEventKind
    node_id: str
    actor_agent: str
    timestamp: str
    payload: dict[str, Any]
    chain_depth: int = 0
    parent_event_id: str | None = None

    @classmethod
    def new(
        cls,
        kind: CoordEventKind,
        node_id: str,
        actor_agent: str,
        payload: dict[str, Any] | None = None,
        *,
        chain_depth: int = 0,
        parent_event_id: str | None = None,
    ) -> "CoordEvent":
        return cls(
            id=str(uuid.uuid4()),
            kind=kind,
            node_id=node_id,
            actor_agent=actor_agent,
            timestamp=datetime.now().isoformat(),
            payload=dict(payload or {}),
            chain_depth=chain_depth,
            parent_event_id=parent_event_id,
        )


class EventBus(Protocol):
    """Minimal contract the CoordinationStore depends on. Implementations
    decide what to do with emitted events (queue them, log them, drop them)."""

    def emit(self, event: CoordEvent) -> None: ...


class NullEventBus:
    """Default for tests and standalone use of the store — emit is a no-op.
    Letting CoordinationStore accept a bus optionally means existing tests
    don't need to plumb one through."""

    def emit(self, event: CoordEvent) -> None:
        return None


class InMemoryEventBus:
    """Thread-safe Queue-backed bus. Suitable for single-process use
    (which is all SOVERYN needs until Spark + multi-machine routing
    becomes a real conversation). Test-friendly: drain() pulls everything
    without blocking."""

    def __init__(self) -> None:
        self._queue: "Queue[CoordEvent]" = Queue()

    def emit(self, event: CoordEvent) -> None:
        self._queue.put(event)

    def get(self, *, timeout: float | None = None) -> CoordEvent:
        return self._queue.get(timeout=timeout)

    def drain(self) -> list[CoordEvent]:
        """Pull every event currently queued. Non-blocking."""
        out: list[CoordEvent] = []
        while not self._queue.empty():
            out.append(self._queue.get_nowait())
        return out

    def task_done(self) -> None:
        self._queue.task_done()

    def join(self) -> None:
        self._queue.join()

    def qsize(self) -> int:
        return self._queue.qsize()


# ─── Thread-local chain context ─────────────────────────────────────────────

_thread_local = threading.local()


@dataclass(frozen=True)
class ChainContext:
    """When a webhook-triggered agent runs, the dispatcher sets the active
    chain context on a thread-local. Tools called during that invocation
    pull from it and stamp their emitted events so chain_depth + parent_id
    propagate correctly. Outside webhook invocations (e.g., user-triggered
    chat), the thread-local is None and events emit at depth 0 with no
    parent."""
    parent_event_id: str
    chain_depth: int


def set_active_chain(context: ChainContext | None) -> None:
    _thread_local.chain = context


def get_active_chain() -> ChainContext | None:
    return getattr(_thread_local, "chain", None)


class chain_context:
    """Context manager: set active chain context for the duration of a
    webhook-triggered agent invocation, restore on exit."""

    def __init__(self, context: ChainContext) -> None:
        self.context = context
        self._previous: ChainContext | None = None

    def __enter__(self) -> "chain_context":
        self._previous = get_active_chain()
        set_active_chain(self.context)
        return self

    def __exit__(self, *exc_info: Any) -> None:
        set_active_chain(self._previous)
