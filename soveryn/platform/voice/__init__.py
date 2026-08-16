"""Sovereign voice — Pipecat-based voice agent for SOVERYN.

Phase 1: Aetheria on ElevenLabs through a modern orchestrator with
VAD-based continuous listening + interruption + sanitization-at-source.
Replaces the patched cloud pipeline from the legacy (pre-vNext) system.

See docs/superpowers/specs/2026-06-10-sovereign-voice-design.md."""

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
