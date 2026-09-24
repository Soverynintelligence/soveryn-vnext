"""Unit tests for KokoroTTSProvider selection — no GPU, no weights load."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from soveryn.platform.voice.providers.kokoro import (
    DEFAULT_VOICE,
    KokoroTTSProvider,
    resolve_kokoro_voice,
)
from soveryn.platform.voice.sovereign_tts import build_tts_service


def test_resolve_kokoro_voice_maps_aetheria():
    assert resolve_kokoro_voice("aetheria") == "af_heart"
    assert resolve_kokoro_voice("Aetheria") == "af_heart"


def test_resolve_kokoro_voice_maps_folded_roster():
    assert resolve_kokoro_voice("eve") == "af_bella"
    assert resolve_kokoro_voice("kernel") == "af_heart"


def test_resolve_kokoro_voice_passthrough_stem():
    assert resolve_kokoro_voice("bf_emma") == "bf_emma"
    assert resolve_kokoro_voice("af_bella") == "af_bella"


def test_resolve_kokoro_voice_env_is_default_not_agent_override(monkeypatch):
    monkeypatch.setenv("SOVERYN_KOKORO_VOICE", "bf_emma")
    assert resolve_kokoro_voice("aetheria") == "af_heart"
    assert resolve_kokoro_voice("eve") == "af_bella"
    assert resolve_kokoro_voice(None) == "bf_emma"


def test_default_voice_is_af_heart():
    assert DEFAULT_VOICE == "af_heart"


def test_provider_name_and_no_gpu_in_constructor():
    provider = KokoroTTSProvider()
    assert provider.name == "kokoro"
    assert provider.sample_rate == 24000


def test_build_tts_service_selects_kokoro(monkeypatch):
    monkeypatch.setenv("SOVEREIGN_TTS_PRIMARY", "kokoro")
    monkeypatch.delenv("SOVERYN_KOKORO_VOICE", raising=False)
    service = build_tts_service(
        agent_name="aetheria",
        elevenlabs_voice_id=None,
        elevenlabs_api_key=None,
    )
    assert service.provider_name == "kokoro"
    assert service.voice_id == "af_heart"
    assert service._native_sample_rate == 24000
    assert service._provider.sample_rate == 24000


def test_build_tts_service_explicit_kokoro_overrides_env(monkeypatch):
    monkeypatch.setenv("SOVEREIGN_TTS_PRIMARY", "f5tts")
    service = build_tts_service(
        agent_name="aetheria",
        elevenlabs_voice_id=None,
        elevenlabs_api_key=None,
        primary="kokoro",
    )
    assert service.provider_name == "kokoro"
    assert service.voice_id == "af_heart"


def test_build_tts_service_eve_uses_kokoro_when_primary_kokoro(monkeypatch):
    monkeypatch.setenv("SOVEREIGN_TTS_PRIMARY", "kokoro")
    monkeypatch.delenv("SOVERYN_KOKORO_VOICE", raising=False)
    service = build_tts_service(
        agent_name="eve",
        elevenlabs_voice_id=None,
        elevenlabs_api_key=None,
    )
    assert service.provider_name == "kokoro"
    assert service.voice_id == "af_bella"


def test_build_tts_service_kernel_uses_f5_clone_when_primary_kokoro(monkeypatch):
    monkeypatch.setenv("SOVEREIGN_TTS_PRIMARY", "kokoro")
    service = build_tts_service(
        agent_name="kernel",
        elevenlabs_voice_id=None,
        elevenlabs_api_key=None,
    )
    assert service.provider_name == "f5tts"
    assert service.voice_id == "kernel"


def test_unknown_primary_mentions_kokoro():
    with pytest.raises(ValueError, match="kokoro"):
        build_tts_service(
            agent_name="aetheria",
            elevenlabs_voice_id="v",
            elevenlabs_api_key="k",
            primary="bogus",
        )
