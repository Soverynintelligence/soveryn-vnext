"""Structured telemetry boundary for audit and review.

Platform and agent actions should produce reviewable events here rather than
ad-hoc logs scattered across subsystems. JSONL is canonical; SQLite is the
query mirror.
"""

from soveryn.platform.telemetry.api import TelemetryError, TelemetryStore, log, query
from soveryn.platform.telemetry.events import TelemetryEvent, TelemetryLevel

__all__ = [
    "TelemetryError",
    "TelemetryEvent",
    "TelemetryLevel",
    "TelemetryStore",
    "log",
    "query",
]
