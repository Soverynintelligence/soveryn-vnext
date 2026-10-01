"""F5-TTS provider — streaming consumer of the local ``f5tts_service``.

The local f5tts_service splits incoming text into clauses, synthesizes each
clause independently, and streams the resulting WAVs back over a single
HTTP response. We decode that framed stream and yield one
:class:`TTSChunk` per clause as it arrives. First-audio latency drops from
"render the whole sentence" (~1.5s for a 3-clause reply) to "render the
first clause" (~700ms).

PR4b (duplex shell): optional ``cancel_event`` / :meth:`abort` so barge-in
can ``aclose`` the HTTP stream and stop emitting PCM. Server-side GPU may
still finish the in-flight clause; remaining clauses are skipped once the
client is gone (server cooperative cancel). Metric:
``clauses_completed_after_cancel``.

Wire format
-----------
Body is a sequence of ``[4-byte big-endian uint32 = N][N bytes of WAV]``
pairs, terminated by a length frame of ``0``. Each WAV chunk is a
complete, self-contained WAV file (header + PCM) so the downstream
``ProviderBackedTTSService`` can decode each chunk independently. See
``f5tts_service/server.py`` for the producer side.
"""

from __future__ import annotations

import asyncio
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
        self._active_response: Any | None = None
        # Clauses received from the server after cancel was observed.
        self.clauses_completed_after_cancel: int = 0
        self._cancel_observed: bool = False

    @property
    def name(self) -> str:
        return "f5tts"

    async def abort(self) -> None:
        """Stop reading the active stream (playout-path cancel).

        Does **not** guarantee the F5 GPU is idle mid-clause — only that we
        stop consuming / emitting audio. Server may still finish the current
        clause then stop (cooperative cancel).
        """
        self._cancel_observed = True
        resp = self._active_response
        if resp is None:
            return
        aclose = getattr(resp, "aclose", None)
        if aclose is None:
            return
        try:
            await aclose()
            logger.info("F5-TTS stream aclose after abort")
        except Exception:  # noqa: BLE001 — cancel path must not raise
            logger.debug("F5-TTS aclose failed", exc_info=True)

    async def synthesize(
        self,
        text: str,
        *,
        voice_id: str,
        cancel_event: asyncio.Event | None = None,
    ) -> AsyncIterator[TTSChunk]:
        if not text.strip():
            return
        if self._http_client is None:
            import httpx

            self._http_client = httpx.AsyncClient(timeout=self.request_timeout)

        self.clauses_completed_after_cancel = 0
        self._cancel_observed = False
        body = {"text": text, "voice": voice_id}
        try:
            async with self._http_client.stream("POST", self.url, json=body) as response:
                self._active_response = response
                try:
                    status = getattr(response, "status_code", None)
                    if status is None:
                        # aiohttp shape — but we use httpx; defensive.
                        status = getattr(response, "status", None)
                    if status != 200:
                        err_body = await response.aread()
                        raise TTSError(
                            f"F5-TTS returned {status}: {err_body[:200]!r}"
                        )

                    async for chunk in _iter_framed(response):
                        if cancel_event is not None and cancel_event.is_set():
                            self._cancel_observed = True
                        if self._cancel_observed:
                            # Frame arrived after cancel (or cancel mid-stream):
                            # count as waste, drop PCM, aclose, stop reading.
                            self.clauses_completed_after_cancel += 1
                            await self.abort()
                            break
                        yield TTSChunk(
                            audio_bytes=chunk,
                            sample_rate=self.sample_rate,
                            is_final=False,
                        )
                finally:
                    self._active_response = None
            # End of stream — emit final marker (even after cancel).
            yield TTSChunk(audio_bytes=b"", sample_rate=self.sample_rate, is_final=True)
        except asyncio.CancelledError:
            self._cancel_observed = True
            await self.abort()
            raise
        except Exception as e:
            if isinstance(e, TTSError):
                raise
            # httpx raises after aclose; treat as clean abort if we cancelled.
            if self._cancel_observed or (
                cancel_event is not None and cancel_event.is_set()
            ):
                logger.debug("F5-TTS stream ended after cancel: %s", e)
                yield TTSChunk(
                    audio_bytes=b"", sample_rate=self.sample_rate, is_final=True
                )
                return
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
    try:
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
    except (asyncio.CancelledError, GeneratorExit):
        raise
    except Exception:
        # Stream closed mid-read (client abort / server drop).
        logger.debug("F5-TTS framed read ended: %s", exc_info=True)
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
