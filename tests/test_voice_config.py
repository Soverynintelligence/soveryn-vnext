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
    # Scotty has no voice character wired yet in Phase 1
    assert cfg.agent_character("scotty") is None
    assert cfg.agent_character("vett") is None


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


def test_aetheria_character_is_none_when_api_key_missing():
    cfg = VoiceConfig.from_env({
        "ELEVENLABS_VOICE_ID_AETHERIA": "voice-id",
        # no API key
    })
    assert cfg.agent_character("aetheria") is None


def test_aetheria_character_is_none_when_voice_id_missing():
    cfg = VoiceConfig.from_env({
        "ELEVENLABS_API_KEY": "key",
        # no voice id
    })
    assert cfg.agent_character("aetheria") is None
