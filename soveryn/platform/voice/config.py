"""Voice config — per-agent voice characters + EnvConfig integration.

Phase 2 (2026-06-15): F5-TTS replaces ElevenLabs as the primary provider.
Roster fold 2026-09-01: Vett's clone rides with Eve, Scotty's with Kernel.
Clones still live in ``~/f5tts_service`` as vett_ref / scotty_ref; F5
keys those files under the live agent names. ``elevenlabs_voice_id`` is
the ElevenLabs fallback only.
"""

from __future__ import annotations
from dataclasses import dataclass


DEFAULT_VOICE_ROOT_NAME = "voice"  # under data_root

VOICE_ENABLED_AGENTS: tuple[str, ...] = ("aetheria", "eve", "kernel")


@dataclass(frozen=True)
class AgentVoiceCharacter:
    """A single agent's voice character config.

    ``elevenlabs_voice_id`` may be None for agents whose only configured
    voice runs on F5-TTS (Eve/Kernel inherited Vett/Scotty clones —
    ElevenLabs IDs were never required).
    """
    agent_name: str
    elevenlabs_voice_id: str | None


@dataclass(frozen=True)
class VoiceConfig:
    """Voice config for the fleet."""
    elevenlabs_api_key: str | None
    aetheria_voice_id: str | None
    eve_voice_id: str | None
    kernel_voice_id: str | None

    @classmethod
    def from_env(cls, env: dict[str, str]) -> "VoiceConfig":
        return cls(
            elevenlabs_api_key=env.get("ELEVENLABS_API_KEY") or None,
            aetheria_voice_id=env.get("ELEVENLABS_VOICE_ID_AETHERIA") or None,
            # New names first; Vett/Scotty env keys still accepted.
            eve_voice_id=(
                env.get("ELEVENLABS_VOICE_ID_EVE")
                or env.get("ELEVENLABS_VOICE_ID_VETT")
                or None
            ),
            kernel_voice_id=(
                env.get("ELEVENLABS_VOICE_ID_KERNEL")
                or env.get("ELEVENLABS_VOICE_ID_SCOTTY")
                or None
            ),
        )

    def agent_character(self, agent_name: str) -> AgentVoiceCharacter | None:
        """Return a character for any agent in ``VOICE_ENABLED_AGENTS``.

        F5-TTS keys on the agent name, so we return a character even when
        the corresponding ElevenLabs ID is missing. The startup layer
        decides whether voice is actually wired (it requires a working
        primary provider; F5-TTS by default, ElevenLabs as fallback).
        """
        agent_name = agent_name.lower().strip()
        if agent_name not in VOICE_ENABLED_AGENTS:
            return None
        voice_id = {
            "aetheria": self.aetheria_voice_id,
            "eve": self.eve_voice_id,
            "kernel": self.kernel_voice_id,
        }[agent_name]
        return AgentVoiceCharacter(
            agent_name=agent_name,
            elevenlabs_voice_id=voice_id,
        )
