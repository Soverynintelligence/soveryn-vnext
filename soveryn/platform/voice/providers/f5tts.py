"""F5-TTS provider — streaming consumer of the local ``f5tts_service``.

The local f5tts_service splits incoming text into clauses, synthesizes each
clause independently, and streams the resulting WAVs back over a single
HTTP response. We decode that framed stream and yield one
:class:`TTSChunk` per clause as it arrives. First-audio latency drops from
"render the whole sentence" (~1.5s for a 3-clause reply) to "render the
first clause" (~700ms).

Wire format
-----------
Body is a sequence of ``[4-byte big-endian uint32 = N][N bytes of WAV]``
pairs, terminated by a length frame of ``0``. Each WAV chunk is a
complete, self-contained WAV file (header + PCM) so the downstream
``ProviderBackedTTSService`` can decode each chunk independently. See
``f5tts_service/server.py`` for the producer side.
"""

from __future__ import annotations

import logging
import struct
from collections.abc import AsyncIterator
from typing import Any

from soveryn.platform.voice.providers.base import TTSChunk, TTSError, TTSProvider


logger = logging.getLogger(__name__)

DEFAULT_URL = "http://127.0.0.1:8088"
DEFAULT_SAMPLE_RATE = 24000  # F5-TTS v1 outputs 24kHz mono


class F5TTSProvider(TTSProvider):
    """HTTP streaming client for the local F5-TTS service.

    The provider does not care about voice cloning details — those live in
    ``f5tts_service``'s voice registry. ``voice_id`` here selects a
    server-side voice name (e.g. ``"aetheria"``).
    """

    def __init__(
        self,
        *,
        url: str = DEFAULT_URL,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        # Injectable for tests
        http_client: Any | None = None,
        request_timeout: float = 120.0,
    ) -> None:
        self.url = url.rstrip("/") + "/synthesize"
        self.sample_rate = sample_rate
        self.request_timeout = request_timeout
        # Lazy httpx construction mirrors ElevenLabsTTSProvider; tests pass
        # a fake client.
        self._http_client = http_client

    @property
    def name(self) -> str:
        return "f5tts"

    async def synthesize(
        self,
        text: str,
        *,
        voice_id: str,
    ) -> AsyncIterator[TTSChunk]:
        if not text.strip():
            return
        if self._http_client is None:
            import httpx

            self._http_client = httpx.AsyncClient(timeout=self.request_timeout)

        body = {"text": text, "voice": voice_id}
        try:
            async with self._http_client.stream("POST", self.url, json=body) as response:
                status = getattr(response, "status_code", None)
                if status is None:
                    # aiohttp shape — but we use httpx; defensive.
                    status = getattr(response, "status", None)
                if status != 200:
                    err_body = await response.aread()
                    raise TTSError(
                        f"F5-TTS returned {status}: {err_body[:200]!r}"
                    )

                # Buffered byte reader over response.aiter_bytes(). The
                # service emits framed chunks but the HTTP layer may split
                # those frames across multiple network reads, so we buffer
                # until we have the next length prefix + payload.
                async for chunk in _iter_framed(response):
                    yield TTSChunk(
                        audio_bytes=chunk,
                        sample_rate=self.sample_rate,
                        is_final=False,
                    )
            # End of stream — emit final marker
            yield TTSChunk(audio_bytes=b"", sample_rate=self.sample_rate, is_final=True)
        except Exception as e:
            if isinstance(e, TTSError):
                raise
            raise TTSError(
                f"F5-TTS synthesis failed: {type(e).__name__}: {e}"
            ) from e


async def _iter_framed(response: Any) -> AsyncIterator[bytes]:
    """Read length-prefixed WAV frames from a streaming HTTP response.

    Each frame is ``[4-byte big-endian uint32 = N][N bytes payload]``.
    A length of 0 marks end-of-stream.
    """
    buf = bytearray()

    async def _drain_one() -> bytes | None:
        nonlocal buf
        if len(buf) < 4:
            return None
        length = struct.unpack(">I", bytes(buf[:4]))[0]
        if length == 0:
            # EOS — consume the terminator and signal done.
            del buf[:4]
            return b""  # sentinel for "EOS reached"
        if len(buf) < 4 + length:
            return None
        payload = bytes(buf[4 : 4 + length])
        del buf[: 4 + length]
        return payload

    eos = False
    async for net_chunk in response.aiter_bytes():
        if not net_chunk:
            continue
        buf.extend(net_chunk)
        while True:
            frame = await _drain_one()
            if frame is None:
                break  # need more bytes from the network
            if frame == b"":
                eos = True
                break
            yield frame
        if eos:
            break
    # If the stream ends without a 0-length terminator, drain whatever
    # complete frames remain in the buffer and return. We don't raise —
    # the server logs the underlying failure; consumers see a truncated
    # but valid sequence of decoded clauses.
    if not eos:
        while True:
            frame = await _drain_one()
            if frame is None or frame == b"":
                break
            yield frame
