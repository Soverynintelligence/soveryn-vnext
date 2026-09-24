"""Sovereign voice — Pipecat-based voice agent for SOVERYN.

See docs/superpowers/specs/2026-06-10-sovereign-voice-design.md and
docs/designs/2026-08-16-duplex-voice-shell.md.

Adapters live in ``soveryn.platform.voice.adapters`` — not re-exported here
to avoid circular imports with ``soveryn.agents.loop`` (which imports
``sanitize`` from this package).
"""

from soveryn.platform.voice.config import (
    AgentVoiceCharacter,
    DEFAULT_VOICE_ROOT_NAME,
    VoiceConfig,
)
from soveryn.platform.voice.duplex_config import DuplexConfig
from soveryn.platform.voice.metrics import TurnMetric, TurnMetricsTracker, emit_turn_metric

__all__ = [
    "AgentVoiceCharacter",
    "DEFAULT_VOICE_ROOT_NAME",
    "DuplexConfig",
    "TurnMetric",
    "TurnMetricsTracker",
    "VoiceConfig",
    "emit_turn_metric",
]
