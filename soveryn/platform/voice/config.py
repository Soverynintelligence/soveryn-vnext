"""Voice config — per-agent voice characters + EnvConfig integration.

Phase 1: Aetheria only (ElevenLabs cloud). Phases 1.5/2 extend this
shape to include Vett and Scotty + local TTS providers."""

from __future__ import annotations
from dataclasses import dataclass


DEFAULT_VOICE_ROOT_NAME = "voice"  # under data_root


@dataclass(frozen=True)
class AgentVoiceCharacter:
    """A single agent's voice character config."""
    agent_name: str
    elevenlabs_voice_id: str | None


@dataclass(frozen=True)
class VoiceConfig:
    """Voice config for the fleet. Phase 1: Aetheria only."""
    elevenlabs_api_key: str | None
    aetheria_voice_id: str | None
    # Phase 1.5 adds vett_voice_id, scotty_voice_id when their characters land

    @classmethod
    def from_env(cls, env: dict[str, str]) -> "VoiceConfig":
        return cls(
            elevenlabs_api_key=env.get("ELEVENLABS_API_KEY") or None,
            aetheria_voice_id=env.get("ELEVENLABS_VOICE_ID_AETHERIA") or None,
        )

    def agent_character(self, agent_name: str) -> AgentVoiceCharacter | None:
        agent_name = agent_name.lower().strip()
        if agent_name == "aetheria":
            if self.elevenlabs_api_key is None or self.aetheria_voice_id is None:
                return None
            return AgentVoiceCharacter(
                agent_name="aetheria",
                elevenlabs_voice_id=self.aetheria_voice_id,
            )
        # Phase 1.5 will return characters for vett + scotty
        return None
