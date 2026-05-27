"""Structured telemetry event shape."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

TelemetryLevel = Literal["debug", "info", "warning", "error"]


@dataclass(frozen=True)
class TelemetryEvent:
    """Reviewable platform or agent action record."""

    source: str
    event_type: str
    level: TelemetryLevel = "info"
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
