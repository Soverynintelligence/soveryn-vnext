"""Per-(sender, target) rate limit for direct_message_agent.

Backstops the schema-layer coord_node_id constraint AND the forensic
lattice-edge audit trail. If a runaway pattern slips past both upstream
layers, this caps the damage and surfaces a structured retry signal
back to the model.

See docs/superpowers/specs/2026-06-05-direct-agent-communication-design.md.
"""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta
from threading import Lock

_WINDOW_SECONDS = 60


class DirectCommRateLimiter:
    """Sliding-window per-(sender, target) cap. Thread-safe.

    Default cap of 8/minute per peer. Independent budgets per
    (sender, target) pair — Aetheria → Vett at cap does NOT affect
    Aetheria → Scotty.
    """

    def __init__(self, *, per_minute_cap: int = 8) -> None:
        self._per_minute_cap = per_minute_cap
        self._calls: dict[tuple[str, str], deque[datetime]] = defaultdict(deque)
        self._lock = Lock()

    def _prune(self, key: tuple[str, str], now: datetime) -> None:
        """Drop calls older than the window. Caller holds the lock."""
        cutoff = now - timedelta(seconds=_WINDOW_SECONDS)
        q = self._calls[key]
        while q and q[0] < cutoff:
            q.popleft()

    def under_cap(self, *, sender: str, target: str, now: datetime) -> bool:
        with self._lock:
            self._prune((sender, target), now)
            return len(self._calls[(sender, target)]) < self._per_minute_cap

    def record(self, *, sender: str, target: str, now: datetime) -> None:
        with self._lock:
            self._prune((sender, target), now)
            self._calls[(sender, target)].append(now)

    def seconds_until_under_cap(
        self, *, sender: str, target: str, now: datetime,
    ) -> int:
        """Returns 0 if already under cap, else seconds until the oldest
        recorded call falls out of the window."""
        with self._lock:
            self._prune((sender, target), now)
            q = self._calls[(sender, target)]
            if len(q) < self._per_minute_cap:
                return 0
            oldest = q[0]
            seconds = _WINDOW_SECONDS - int((now - oldest).total_seconds())
            return max(seconds, 0)
