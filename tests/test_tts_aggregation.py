"""PR3 — TTS TextAggregationMode wiring."""

from __future__ import annotations

from pipecat.services.tts_service import TextAggregationMode

from soveryn.platform.voice.sovereign_tts import (
    ProviderBackedTTSService,
    build_tts_service,
    resolve_text_aggregation_mode,
)


def test_resolve_text_aggregation_mode():
    assert resolve_text_aggregation_mode("token") == TextAggregationMode.TOKEN
    assert resolve_text_aggregation_mode("sentence") == TextAggregationMode.SENTENCE
    assert resolve_text_aggregation_mode(None) == TextAggregationMode.TOKEN
    assert resolve_text_aggregation_mode("SENT") == TextAggregationMode.SENTENCE


def test_build_tts_service_token_mode_default(monkeypatch):
    monkeypatch.setenv("SOVEREIGN_TTS_PRIMARY", "f5tts")
    monkeypatch.delenv("SOVERYN_VOICE_TTS_AGG", raising=False)
    svc = build_tts_service(
        agent_name="aetheria",
        elevenlabs_voice_id=None,
        elevenlabs_api_key=None,
    )
    assert isinstance(svc, ProviderBackedTTSService)
    assert svc.text_aggregation_mode == TextAggregationMode.TOKEN
    assert svc.voice_id == "aetheria"


def test_build_tts_service_sentence_mode(monkeypatch):
    monkeypatch.setenv("SOVEREIGN_TTS_PRIMARY", "f5tts")
    svc = build_tts_service(
        agent_name="aetheria",
        elevenlabs_voice_id=None,
        elevenlabs_api_key=None,
        tts_agg="sentence",
    )
    assert svc.text_aggregation_mode == TextAggregationMode.SENTENCE
