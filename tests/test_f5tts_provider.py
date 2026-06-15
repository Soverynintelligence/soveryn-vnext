"""Tests for ``F5TTSProvider``.

Mirrors the ``test_voice_elevenlabs_provider.py`` pattern: fake httpx-shape
client + async-streaming response object, ``asyncio.run`` wrapper around
each async test body (pytest-asyncio is not installed in the soveryn env).

Wire format under test: ``[4-byte BE length N][N bytes payload]*`` with a
``0``-length terminator. The framing decoder must handle arbitrary network
chunking (the test feeds bytes one-byte-at-a-time in one case to exercise
the resume-across-net-reads path).
"""

from __future__ import annotations

import asyncio
import struct

import pytest

from soveryn.platform.voice.providers.base import TTSError
from soveryn.platform.voice.providers.f5tts import (
    DEFAULT_SAMPLE_RATE,
    F5TTSProvider,
)


def _frame(payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + payload


def _eos() -> bytes:
    return struct.pack(">I", 0)


class FakeAsyncStreamingResponse:
    def __init__(self, status_code: int, chunks: list[bytes]):
        self.status_code = status_code
        self._chunks = chunks

    async def aiter_bytes(self):
        for c in self._chunks:
            yield c

    async def aread(self):
        return b"".join(self._chunks)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None


class FakeHTTPClient:
    def __init__(self, response: FakeAsyncStreamingResponse):
        self.response = response
        self.calls: list[dict] = []

    def stream(self, method, url, *, json):
        self.calls.append({"method": method, "url": url, "json": json})
        return self.response


# ---------------------------------------------------------------------------
# Wire-format decoding
# ---------------------------------------------------------------------------


def test_synthesize_yields_chunk_per_wav_frame():
    async def run():
        body = _frame(b"WAV1") + _frame(b"WAVE-2-BIGGER") + _eos()
        fake = FakeHTTPClient(FakeAsyncStreamingResponse(200, [body]))
        provider = F5TTSProvider(http_client=fake)
        chunks = []
        async for chunk in provider.synthesize("hello", voice_id="aetheria"):
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(run())
    # Two audio chunks + one final-marker chunk
    assert len(chunks) == 3
    assert chunks[0].audio_bytes == b"WAV1"
    assert chunks[0].is_final is False
    assert chunks[0].sample_rate == DEFAULT_SAMPLE_RATE
    assert chunks[1].audio_bytes == b"WAVE-2-BIGGER"
    assert chunks[1].is_final is False
    assert chunks[2].audio_bytes == b""
    assert chunks[2].is_final is True


def test_synthesize_handles_frame_split_across_network_reads():
    """Network IO doesn't respect framing — feed bytes one at a time and
    verify the decoder buffers them correctly."""
    async def run():
        body = _frame(b"abcdefgh") + _frame(b"xyz") + _eos()
        # Deliver one byte per network chunk to maximize fragmentation.
        net_chunks = [body[i:i+1] for i in range(len(body))]
        fake = FakeHTTPClient(FakeAsyncStreamingResponse(200, net_chunks))
        provider = F5TTSProvider(http_client=fake)
        out = []
        async for chunk in provider.synthesize("ok", voice_id="aetheria"):
            if not chunk.is_final:
                out.append(chunk.audio_bytes)
        return out

    out = asyncio.run(run())
    assert out == [b"abcdefgh", b"xyz"]


def test_synthesize_handles_multiple_frames_in_single_network_read():
    """The opposite of the previous test — one big network read covers
    multiple framed chunks. Decoder must drain all complete frames."""
    async def run():
        body = _frame(b"A") + _frame(b"BB") + _frame(b"CCC") + _eos()
        fake = FakeHTTPClient(FakeAsyncStreamingResponse(200, [body]))
        provider = F5TTSProvider(http_client=fake)
        out = []
        async for chunk in provider.synthesize("ok", voice_id="aetheria"):
            if not chunk.is_final:
                out.append(chunk.audio_bytes)
        return out

    assert asyncio.run(run()) == [b"A", b"BB", b"CCC"]


def test_synthesize_emits_is_final_terminator_after_stream_end():
    async def run():
        body = _frame(b"only") + _eos()
        fake = FakeHTTPClient(FakeAsyncStreamingResponse(200, [body]))
        provider = F5TTSProvider(http_client=fake)
        chunks = []
        async for chunk in provider.synthesize("ok", voice_id="aetheria"):
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(run())
    assert chunks[-1].is_final is True
    assert chunks[-1].audio_bytes == b""


# ---------------------------------------------------------------------------
# Empty input + URL + voice routing
# ---------------------------------------------------------------------------


def test_empty_text_yields_no_chunks_and_does_not_call_api():
    async def run():
        fake = FakeHTTPClient(FakeAsyncStreamingResponse(200, [_eos()]))
        provider = F5TTSProvider(http_client=fake)
        chunks = []
        async for chunk in provider.synthesize("   ", voice_id="aetheria"):
            chunks.append(chunk)
        return chunks, fake

    chunks, fake = asyncio.run(run())
    assert chunks == []
    assert fake.calls == []


def test_synthesize_posts_to_synthesize_path():
    async def run():
        fake = FakeHTTPClient(FakeAsyncStreamingResponse(200, [_frame(b"x") + _eos()]))
        provider = F5TTSProvider(
            url="http://127.0.0.1:8088",
            http_client=fake,
        )
        async for _ in provider.synthesize("hi", voice_id="aetheria"):
            pass
        return fake

    fake = asyncio.run(run())
    assert fake.calls[0]["url"] == "http://127.0.0.1:8088/synthesize"
    assert fake.calls[0]["method"] == "POST"


def test_synthesize_url_strips_trailing_slash():
    provider = F5TTSProvider(url="http://127.0.0.1:8088/")
    assert provider.url == "http://127.0.0.1:8088/synthesize"


def test_synthesize_sends_text_and_voice_in_body():
    async def run():
        fake = FakeHTTPClient(FakeAsyncStreamingResponse(200, [_frame(b"x") + _eos()]))
        provider = F5TTSProvider(http_client=fake)
        async for _ in provider.synthesize("hello world", voice_id="aetheria"):
            pass
        return fake

    fake = asyncio.run(run())
    body = fake.calls[0]["json"]
    assert body == {"text": "hello world", "voice": "aetheria"}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


def test_synthesize_raises_on_non_200():
    async def run():
        fake = FakeHTTPClient(FakeAsyncStreamingResponse(503, [b'{"error":"down"}']))
        provider = F5TTSProvider(http_client=fake)
        async for _ in provider.synthesize("hi", voice_id="aetheria"):
            pass

    with pytest.raises(TTSError, match="503"):
        asyncio.run(run())


def test_truncated_stream_yields_decoded_frames_then_stops():
    """If the server dies mid-stream without sending the 0-length
    terminator, the provider must yield whatever complete frames it has
    and exit cleanly — not hang forever waiting for more bytes."""

    async def run():
        # First frame complete, second frame's length prefix says 100 but only
        # 4 bytes follow before the stream ends. We expect one yield (the
        # first complete frame) and then graceful EOS without raising.
        body = _frame(b"complete") + struct.pack(">I", 100) + b"frag"
        fake = FakeHTTPClient(FakeAsyncStreamingResponse(200, [body]))
        provider = F5TTSProvider(http_client=fake)
        out = []
        async for chunk in provider.synthesize("hi", voice_id="aetheria"):
            out.append(chunk)
        return out

    out = asyncio.run(run())
    # First chunk decoded; final marker emitted (after the underlying stream
    # exhausted without a 0-terminator). No partial chunk surfaced.
    audio_chunks = [c for c in out if not c.is_final]
    assert [c.audio_bytes for c in audio_chunks] == [b"complete"]
    assert out[-1].is_final is True


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def test_name_is_f5tts():
    assert F5TTSProvider().name == "f5tts"


def test_default_sample_rate_is_24khz():
    p = F5TTSProvider()
    assert p.sample_rate == 24000
