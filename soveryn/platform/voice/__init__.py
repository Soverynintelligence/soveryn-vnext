"""Sovereign voice — Pipecat-based voice agent for SOVERYN.

Phase 1: Aetheria on ElevenLabs through a modern orchestrator with
VAD-based continuous listening + interruption + sanitization-at-source.
Replaces the patched cloud pipeline from soveryn_complete.

See docs/superpowers/specs/2026-06-10-sovereign-voice-design.md."""

from soveryn.platform.voice.config import (
    AgentVoiceCharacter,
    DEFAULT_VOICE_ROOT_NAME,
    VoiceConfig,
)

__all__ = [
    "AgentVoiceCharacter",
    "DEFAULT_VOICE_ROOT_NAME",
    "VoiceConfig",
]
