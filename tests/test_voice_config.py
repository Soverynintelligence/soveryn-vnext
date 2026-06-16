"""Tests for soveryn.platform.voice.config + EnvConfig voice fields."""

from pathlib import Path

from soveryn.platform.voice import (
    AgentVoiceCharacter,
    DEFAULT_VOICE_ROOT_NAME,
    VoiceConfig,
)
from soveryn.config.loader import load_env_config


def test_voice_config_for_aetheria_uses_env_voice_id():
    cfg = VoiceConfig.from_env({
        "ELEVENLABS_API_KEY": "test-key",
        "ELEVENLABS_VOICE_ID_AETHERIA": "voice-aetheria-id",
    })
    aetheria = cfg.agent_character("aetheria")
    assert aetheria is not None
    assert isinstance(aetheria, AgentVoiceCharacter)
    assert aetheria.agent_name == "aetheria"
    assert aetheria.elevenlabs_voice_id == "voice-aetheria-id"


def test_voice_config_returns_none_for_unconfigured_agent():
    cfg = VoiceConfig.from_env({
        "ELEVENLABS_API_KEY": "key",
        "ELEVENLABS_VOICE_ID_AETHERIA": "voice-aetheria-id",
    })
    # Agents not in VOICE_ENABLED_AGENTS (aetheria/vett/scotty) get None.
    # Phase 2 (F5-TTS): all three named agents are now voice-enabled.
    assert cfg.agent_character("ares") is None
    assert cfg.agent_character("heartbeat") is None


def test_env_config_has_voice_fields():
    cfg = load_env_config({
        "ELEVENLABS_API_KEY": "k",
        "ELEVENLABS_VOICE_ID_AETHERIA": "va",
    })
    assert cfg.elevenlabs_api_key == "k"
    assert cfg.elevenlabs_voice_id_aetheria == "va"
    assert cfg.voice_root == cfg.data_root / DEFAULT_VOICE_ROOT_NAME


def test_voice_root_derives_from_data_root_cascade():
    cfg = load_env_config({"SOVERYN_DATA_ROOT": "/tmp/custom"})
    assert cfg.voice_root == Path("/tmp/custom/voice")


def test_voice_root_explicit_env_override_wins():
    cfg = load_env_config({
        "SOVERYN_DATA_ROOT": "/tmp/custom",
        "SOVERYN_VOICE_ROOT": "/other/voice/path",
    })
    assert cfg.voice_root == Path("/other/voice/path")


def test_aetheria_character_present_without_api_key_under_f5tts():
    """Phase 2 (F5-TTS): agent character is returned even without ELEVENLABS_API_KEY.
    F5-TTS keys on agent name, not ElevenLabs creds. elevenlabs_voice_id
    reflects the configured ElevenLabs voice ID (for the fallback path)."""
    cfg = VoiceConfig.from_env({
        "ELEVENLABS_VOICE_ID_AETHERIA": "voice-id",
        # no API key — voice still works via F5-TTS
    })
    char = cfg.agent_character("aetheria")
    assert char is not None
    assert char.elevenlabs_voice_id == "voice-id"


def test_aetheria_character_present_with_elevenlabs_voice_id_none():
    """Phase 2 (F5-TTS): a character is returned even when no ElevenLabs voice ID
    is set. elevenlabs_voice_id is None (F5-TTS doesn't need it)."""
    cfg = VoiceConfig.from_env({
        "ELEVENLABS_API_KEY": "key",
        # no voice id — still voice-enabled via F5-TTS
    })
    char = cfg.agent_character("aetheria")
    assert char is not None
    assert char.elevenlabs_voice_id is None
