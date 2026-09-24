"""Tests for ``ProviderBackedTTSService`` + ``build_tts_service``.

The Pipecat wrapper takes a TTSProvider, decodes the WAV chunks it
streams, and emits one ``TTSAudioRawFrame`` per chunk plus
``TTSStartedFrame`` / ``TTSStoppedFrame`` brackets.

We use a fake provider so the test stays unit-scoped and never hits the
F5-TTS service or the cloud.
"""

from __future__ import annotations

import asyncio
import io
import os
import struct
from collections.abc import AsyncIterator

import numpy as np
import pytest
import soundfile as sf

from pipecat.frames.frames import (
    ErrorFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)

from soveryn.platform.voice.providers.base import TTSChunk, TTSError, TTSProvider
from soveryn.platform.voice.sovereign_tts import (
    DEFAULT_PRIMARY,
    ProviderBackedTTSService,
    build_tts_service,
)


def _make_wav_bytes(samples: int = 480, sample_rate: int = 24000) -> bytes:
    """Tiny mono int16 WAV with a sawtooth so we can sanity-check shape."""
    wave = (np.arange(samples) % 256 - 128).astype(np.int16)
    buf = io.BytesIO()
    sf.write(buf, wave, sample_rate, format="WAV", subtype="PCM_16")
    return buf.getvalue()


class _FakeProvider(TTSProvider):
    def __init__(self, chunks: list[TTSChunk], *, raise_after: int | None = None):
        self._chunks = chunks
        self._raise_after = raise_after
        self.calls: list[tuple[str, str]] = []

    @property
    def name(self) -> str:
        return "fake"

    async def synthesize(self, text: str, *, voice_id: str) -> AsyncIterator[TTSChunk]:
        self.calls.append((text, voice_id))
        for i, c in enumerate(self._chunks):
            if self._raise_after is not None and i == self._raise_after:
                raise TTSError("simulated failure")
            yield c


async def _drain(service: ProviderBackedTTSService, text: str) -> list:
    out = []
    async for frame in service.run_tts(text, "ctx-1"):
        if frame is not None:
            out.append(frame)
    return out


# ---------------------------------------------------------------------------
# Frame emission
# ---------------------------------------------------------------------------


def test_run_tts_emits_started_audio_stopped():
    wav = _make_wav_bytes()
    provider = _FakeProvider([
        TTSChunk(audio_bytes=wav, sample_rate=24000, is_final=False),
        TTSChunk(audio_bytes=b"", sample_rate=24000, is_final=True),
    ])
    service = ProviderBackedTTSService(
        provider=provider, voice_id="aetheria", sample_rate=24000,
    )
    frames = asyncio.run(_drain(service, "hello"))
    types = [type(f).__name__ for f in frames]

    assert types[0] == "TTSStartedFrame"
    assert types[-1] == "TTSStoppedFrame"
    audio_frames = [f for f in frames if isinstance(f, TTSAudioRawFrame)]
    assert len(audio_frames) == 1
    assert audio_frames[0].sample_rate == 24000
    assert audio_frames[0].num_channels == 1
    # 480 samples * 2 bytes/sample = 960 bytes of raw int16 PCM
    assert len(audio_frames[0].audio) == 960


def test_run_tts_emits_one_audio_frame_per_provider_chunk():
    chunks = [
        TTSChunk(audio_bytes=_make_wav_bytes(samples=100), sample_rate=24000, is_final=False),
        TTSChunk(audio_bytes=_make_wav_bytes(samples=200), sample_rate=24000, is_final=False),
        TTSChunk(audio_bytes=_make_wav_bytes(samples=300), sample_rate=24000, is_final=False),
        TTSChunk(audio_bytes=b"", sample_rate=24000, is_final=True),
    ]
    provider = _FakeProvider(chunks)
    service = ProviderBackedTTSService(
        provider=provider, voice_id="aetheria", sample_rate=24000,
    )
    frames = asyncio.run(_drain(service, "three clauses please"))
    audio = [f for f in frames if isinstance(f, TTSAudioRawFrame)]
    assert len(audio) == 3
    # 100, 200, 300 samples * 2 bytes
    assert [len(f.audio) for f in audio] == [200, 400, 600]


def test_run_tts_skips_final_marker_and_empty_audio():
    chunks = [
        TTSChunk(audio_bytes=_make_wav_bytes(), sample_rate=24000, is_final=False),
        TTSChunk(audio_bytes=b"", sample_rate=24000, is_final=False),  # bogus empty
        TTSChunk(audio_bytes=b"", sample_rate=24000, is_final=True),
    ]
    provider = _FakeProvider(chunks)
    service = ProviderBackedTTSService(
        provider=provider, voice_id="v", sample_rate=24000,
    )
    frames = asyncio.run(_drain(service, "ok"))
    audio = [f for f in frames if isinstance(f, TTSAudioRawFrame)]
    assert len(audio) == 1  # the empty + final chunks both filtered


def test_run_tts_empty_text_returns_nothing():
    provider = _FakeProvider([])
    service = ProviderBackedTTSService(
        provider=provider, voice_id="v", sample_rate=24000,
    )
    frames = asyncio.run(_drain(service, "   "))
    assert frames == []
    assert provider.calls == []  # provider never invoked


def test_run_tts_passes_voice_id_to_provider():
    chunks = [TTSChunk(audio_bytes=b"", sample_rate=24000, is_final=True)]
    provider = _FakeProvider(chunks)
    service = ProviderBackedTTSService(
        provider=provider, voice_id="aetheria", sample_rate=24000,
    )
    asyncio.run(_drain(service, "hi there"))
    assert provider.calls == [("hi there", "aetheria")]


def test_run_tts_emits_error_frame_and_still_stops_on_provider_failure():
    wav = _make_wav_bytes()
    provider = _FakeProvider(
        [TTSChunk(audio_bytes=wav, sample_rate=24000, is_final=False),
         TTSChunk(audio_bytes=wav, sample_rate=24000, is_final=False)],
        raise_after=1,
    )
    service = ProviderBackedTTSService(
        provider=provider, voice_id="v", sample_rate=24000,
    )
    frames = asyncio.run(_drain(service, "fail mid stream"))
    types = [type(f).__name__ for f in frames]
    assert "TTSStartedFrame" in types
    assert "TTSStoppedFrame" in types
    # The first chunk was emitted before the failure
    assert any(isinstance(f, TTSAudioRawFrame) for f in frames)
    # An ErrorFrame carrying the provider failure surfaced
    err = [f for f in frames if isinstance(f, ErrorFrame)]
    assert err and "simulated failure" in err[0].error


# ---------------------------------------------------------------------------
# Identity / construction
# ---------------------------------------------------------------------------


def test_provider_name_and_voice_id_expose_through_service():
    provider = _FakeProvider([])
    service = ProviderBackedTTSService(
        provider=provider, voice_id="aetheria", sample_rate=24000,
    )
    assert service.provider_name == "fake"
    assert service.voice_id == "aetheria"


# ---------------------------------------------------------------------------
# build_tts_service — provider selection
# ---------------------------------------------------------------------------


def test_build_tts_service_defaults_to_f5tts():
    prior = os.environ.pop("SOVEREIGN_TTS_PRIMARY", None)
    try:
        service = build_tts_service(
            agent_name="aetheria",
            elevenlabs_voice_id=None,
            elevenlabs_api_key=None,
        )
        assert service.provider_name == "f5tts"
        assert service.voice_id == "aetheria"
    finally:
        if prior is not None:
            os.environ["SOVEREIGN_TTS_PRIMARY"] = prior


def test_build_tts_service_env_selects_elevenlabs():
    prior = os.environ.get("SOVEREIGN_TTS_PRIMARY")
    os.environ["SOVEREIGN_TTS_PRIMARY"] = "elevenlabs"
    try:
        service = build_tts_service(
            agent_name="aetheria",
            elevenlabs_voice_id="cloud-voice-id",
            elevenlabs_api_key="sk-test",
        )
        assert service.provider_name == "elevenlabs"
        assert service.voice_id == "cloud-voice-id"
    finally:
        if prior is None:
            os.environ.pop("SOVEREIGN_TTS_PRIMARY", None)
        else:
            os.environ["SOVEREIGN_TTS_PRIMARY"] = prior


def test_build_tts_service_elevenlabs_requires_api_key():
    prior = os.environ.get("SOVEREIGN_TTS_PRIMARY")
    os.environ["SOVEREIGN_TTS_PRIMARY"] = "elevenlabs"
    try:
        with pytest.raises(ValueError, match="elevenlabs_api_key"):
            build_tts_service(
                agent_name="aetheria",
                elevenlabs_voice_id="v",
                elevenlabs_api_key=None,
            )
    finally:
        if prior is None:
            os.environ.pop("SOVEREIGN_TTS_PRIMARY", None)
        else:
            os.environ["SOVEREIGN_TTS_PRIMARY"] = prior


def test_build_tts_service_explicit_primary_overrides_env():
    prior = os.environ.get("SOVEREIGN_TTS_PRIMARY")
    os.environ["SOVEREIGN_TTS_PRIMARY"] = "elevenlabs"
    try:
        service = build_tts_service(
            agent_name="aetheria",
            elevenlabs_voice_id=None,
            elevenlabs_api_key=None,
            primary="f5tts",
        )
        assert service.provider_name == "f5tts"
    finally:
        if prior is None:
            os.environ.pop("SOVEREIGN_TTS_PRIMARY", None)
        else:
            os.environ["SOVEREIGN_TTS_PRIMARY"] = prior


def test_build_tts_service_unknown_primary_raises():
    with pytest.raises(ValueError, match="unknown SOVEREIGN_TTS_PRIMARY"):
        build_tts_service(
            agent_name="aetheria",
            elevenlabs_voice_id="v",
            elevenlabs_api_key="k",
            primary="bogus",
        )


def test_default_primary_is_f5tts():
    assert DEFAULT_PRIMARY == "f5tts"


def test_build_tts_service_env_selects_kokoro():
    prior = os.environ.get("SOVEREIGN_TTS_PRIMARY")
    os.environ["SOVEREIGN_TTS_PRIMARY"] = "kokoro"
    try:
        service = build_tts_service(
            agent_name="aetheria",
            elevenlabs_voice_id=None,
            elevenlabs_api_key=None,
        )
        assert service.provider_name == "kokoro"
        assert service.voice_id == "af_heart"
    finally:
        if prior is None:
            os.environ.pop("SOVEREIGN_TTS_PRIMARY", None)
        else:
            os.environ["SOVEREIGN_TTS_PRIMARY"] = prior
