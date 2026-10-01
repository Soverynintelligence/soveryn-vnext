"""TTS TextAggregationMode wiring — F5 keeps SENTENCE; adapter holds ~320."""

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
    assert resolve_text_aggregation_mode(None) == TextAggregationMode.SENTENCE
    assert resolve_text_aggregation_mode("SENT") == TextAggregationMode.SENTENCE


def test_f5_keeps_sentence_aggregation(monkeypatch):
    """F5 keeps SENTENCE; adapter 320-hold makes a normal reply one clip.

    TOKEN fragments each became a full HTTP synth and slurred Aetheria.
    """
    monkeypatch.setenv("SOVEREIGN_TTS_PRIMARY", "f5tts")
    monkeypatch.delenv("SOVERYN_VOICE_TTS_AGG", raising=False)
    svc = build_tts_service(
        agent_name="aetheria",
        elevenlabs_voice_id=None,
        elevenlabs_api_key=None,
    )
    assert isinstance(svc, ProviderBackedTTSService)
    assert svc.text_aggregation_mode == TextAggregationMode.SENTENCE
    assert svc.voice_id == "aetheria"


def test_f5_honors_sentence_aggregation(monkeypatch):
    monkeypatch.setenv("SOVEREIGN_TTS_PRIMARY", "f5tts")
    svc = build_tts_service(
        agent_name="aetheria",
        elevenlabs_voice_id=None,
        elevenlabs_api_key=None,
        tts_agg="sentence",
    )
    assert svc.text_aggregation_mode == TextAggregationMode.SENTENCE


def test_adapter_single_flush_for_normal_reply():
    """Whole turn one clip — no mid-reply silence after first sentence."""
    import asyncio

    from soveryn.agents.loop import TTSTokenEvent
    from soveryn.platform.voice.adapters.agent_loop import AgentLoopAdapter

    class FakeLoop:
        def process_message_stream(self, sid, msg, **kw):
            for t in [
                "I'm here. ",
                "Ready when you are. ",
                "Still in that Sunday pocket. ",
                "You?",
            ]:
                yield TTSTokenEvent(text=t)

    async def main():
        a = AgentLoopAdapter(
            FakeLoop(), agent_id="aetheria", tts_agg="sentence", flush_chars=40
        )
        chunks = []
        async for c in a.start_turn(
            session_id="s",
            user_text="hi",
            cancel_event=asyncio.Event(),
            turn_epoch=1,
        ):
            chunks.append(c.text)
        return chunks

    chunks = asyncio.run(main())
    assert len(chunks) == 1, chunks
    assert "I'm here" in chunks[0] and "Sunday" in chunks[0]
