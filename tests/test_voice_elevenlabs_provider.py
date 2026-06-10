"""Tests for ``ElevenLabsTTSProvider``.

``pytest-asyncio`` is not installed in the soveryn conda env, so each
async test body is wrapped in ``asyncio.run(...)`` from a sync test
function. The fake HTTP client / response classes match the plan's
``FakeAsyncStreamingResponse`` / ``FakeHTTPClient`` shape exactly."""

from __future__ import annotations

import asyncio

import pytest

from soveryn.platform.voice.providers.base import TTSChunk, TTSError
from soveryn.platform.voice.providers.elevenlabs import (
    DEFAULT_MODEL_ID,
    DEFAULT_SAMPLE_RATE,
    ELEVENLABS_STREAM_URL,
    ElevenLabsTTSProvider,
)


class FakeAsyncStreamingResponse:
    def __init__(self, status_code, chunks):
        self.status_code = status_code
        self._chunks = chunks

    async def aiter_bytes(self, chunk_size):
        for c in self._chunks:
            yield c

    async def aread(self):
        return b"".join(self._chunks)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pass


class FakeHTTPClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def stream(self, method, url, headers, json):
        self.calls.append(
            {"method": method, "url": url, "headers": headers, "json": json}
        )
        return self.response


def test_synthesize_yields_audio_chunks():
    async def run():
        fake_response = FakeAsyncStreamingResponse(200, [b"abc", b"def"])
        fake_http = FakeHTTPClient(fake_response)
        provider = ElevenLabsTTSProvider(api_key="k", http_client=fake_http)
        chunks = []
        async for chunk in provider.synthesize("hello", voice_id="voice-1"):
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(run())
    # Two audio chunks + one final-marker chunk
    assert len(chunks) == 3
    assert chunks[0].audio_bytes == b"abc"
    assert chunks[0].is_final is False
    assert chunks[1].audio_bytes == b"def"
    assert chunks[1].is_final is False
    assert chunks[2].audio_bytes == b""
    assert chunks[2].is_final is True


def test_synthesize_uses_correct_voice_id_in_url():
    async def run():
        fake_response = FakeAsyncStreamingResponse(200, [b"audio"])
        fake_http = FakeHTTPClient(fake_response)
        provider = ElevenLabsTTSProvider(api_key="k", http_client=fake_http)
        async for _ in provider.synthesize("hi", voice_id="my-voice-xyz"):
            pass
        return fake_http

    fake_http = asyncio.run(run())
    assert "my-voice-xyz" in fake_http.calls[0]["url"]
    # Sanity: matches the canonical URL template
    assert fake_http.calls[0]["url"] == ELEVENLABS_STREAM_URL.format(
        voice_id="my-voice-xyz"
    )


def test_synthesize_raises_on_error_status():
    async def run():
        fake_response = FakeAsyncStreamingResponse(429, [b'{"error":"rate limit"}'])
        fake_http = FakeHTTPClient(fake_response)
        provider = ElevenLabsTTSProvider(api_key="k", http_client=fake_http)
        async for _ in provider.synthesize("hi", voice_id="v"):
            pass

    with pytest.raises(TTSError, match="429"):
        asyncio.run(run())


def test_synthesize_empty_text_yields_nothing():
    async def run():
        fake_response = FakeAsyncStreamingResponse(200, [b"audio"])
        fake_http = FakeHTTPClient(fake_response)
        provider = ElevenLabsTTSProvider(api_key="k", http_client=fake_http)
        chunks = []
        async for chunk in provider.synthesize("   ", voice_id="v"):
            chunks.append(chunk)
        return chunks, fake_http

    chunks, fake_http = asyncio.run(run())
    assert chunks == []
    assert fake_http.calls == []  # never called the API


def test_constructor_rejects_empty_api_key():
    with pytest.raises(ValueError, match="api_key"):
        ElevenLabsTTSProvider(api_key="")


def test_name_is_elevenlabs():
    provider = ElevenLabsTTSProvider(api_key="k")
    assert provider.name == "elevenlabs"


def test_synthesize_uses_model_id_in_body():
    async def run():
        fake_response = FakeAsyncStreamingResponse(200, [b"audio"])
        fake_http = FakeHTTPClient(fake_response)
        provider = ElevenLabsTTSProvider(api_key="k", http_client=fake_http)
        async for _ in provider.synthesize("hi", voice_id="v"):
            pass
        return fake_http

    fake_http = asyncio.run(run())
    body = fake_http.calls[0]["json"]
    assert body["model_id"] == DEFAULT_MODEL_ID
    assert body["text"] == "hi"
    assert body["voice_settings"]["stability"] == 0.5
    assert body["voice_settings"]["similarity_boost"] == 0.8


def test_synthesize_default_sample_rate_propagates_to_chunks():
    async def run():
        fake_response = FakeAsyncStreamingResponse(200, [b"abc", b"def", b"ghi"])
        fake_http = FakeHTTPClient(fake_response)
        provider = ElevenLabsTTSProvider(api_key="k", http_client=fake_http)
        chunks: list[TTSChunk] = []
        async for chunk in provider.synthesize("hello", voice_id="v"):
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(run())
    assert chunks, "expected at least one chunk"
    for chunk in chunks:
        assert chunk.sample_rate == DEFAULT_SAMPLE_RATE
