"""Structured telemetry boundary for audit and review.

Platform and agent actions should produce reviewable events here rather than
ad-hoc logs scattered across subsystems. Phase 1 declares the event shape only.
"""

from soveryn.platform.telemetry.events import TelemetryEvent, TelemetryLevel

__all__ = ["TelemetryEvent", "TelemetryLevel"]
