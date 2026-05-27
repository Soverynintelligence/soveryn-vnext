"""Aetheria heartbeat entry surface.

Heartbeat is intentionally separate from chat. Phase 1 declares the boundary and
state ownership; the production heartbeat behavior is ported in a later phase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class HeartbeatNotPortedError(NotImplementedError):
    """Raised when heartbeat execution is requested before the port exists."""


@dataclass
class HeartbeatSurfaceState:
    """Mutable state owned by the heartbeat surface only."""

    ticks_seen: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class AetheriaHeartbeatSurface:
    """Declared heartbeat entry point. Real behavior is deferred."""

    def __init__(self, state: HeartbeatSurfaceState | None = None) -> None:
        self.state = state or HeartbeatSurfaceState()

    def tick(self) -> None:
        self.state.ticks_seen += 1
        raise HeartbeatNotPortedError("Aetheria heartbeat surface is declared, not ported in Phase 1")
