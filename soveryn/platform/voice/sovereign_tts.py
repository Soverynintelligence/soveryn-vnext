"""Pipecat TTSService wrapper around the :class:`TTSProvider` abstraction.

This is the bridge between SOVERYN's transport-agnostic provider layer
(``soveryn.platform.voice.providers``) and Pipecat's pipeline. The
provider streams audio chunks; we decode each chunk and emit it as a
``TTSAudioRawFrame`` so Pipecat's transport can ship it to the browser.

Provider selection
------------------
``build_tts_service`` reads the ``SOVEREIGN_TTS_PRIMARY`` env var to pick
between providers:

- ``f5tts`` (default): :class:`F5TTSProvider`, talking to the local
  service on ``F5TTS_URL`` (default ``http://127.0.0.1:8088``).
- ``elevenlabs``: :class:`ElevenLabsTTSProvider`, the cloud fallback.

Cutover / rollback is a single env-var change — no code changes required.
"""

from __future__ import annotations

import io
import logging
import os
from collections.abc import AsyncGenerator
from typing import Any

from pipecat.frames.frames import (
    ErrorFrame,
    Frame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.services.tts_service import TTSService

from soveryn.platform.voice.providers.base import TTSError, TTSProvider
from soveryn.platform.voice.providers.elevenlabs import (
    DEFAULT_SAMPLE_RATE as ELEVENLABS_SAMPLE_RATE,
    ElevenLabsTTSProvider,
)
from soveryn.platform.voice.providers.f5tts import (
    DEFAULT_SAMPLE_RATE as F5TTS_SAMPLE_RATE,
    DEFAULT_URL as F5TTS_DEFAULT_URL,
    F5TTSProvider,
)


logger = logging.getLogger(__name__)

DEFAULT_PRIMARY = "f5tts"


class ProviderBackedTTSService(TTSService):
    """Pipecat TTSService that delegates to a :class:`TTSProvider`.

    Each chunk emitted by the provider is decoded (WAV -> int16 PCM) and
    pushed as a ``TTSAudioRawFrame`` with the provider's sample rate.

    Pipecat 1.3.0's ``TTSService.run_tts`` signature is
    ``(text, context_id)``; we don't currently use the context_id, but we
    accept it so we stay compatible with the abstract method.
    """

    def __init__(
        self,
        *,
        provider: TTSProvider,
        voice_id: str,
        sample_rate: int,
        **kwargs: Any,
    ) -> None:
        super().__init__(sample_rate=sample_rate, **kwargs)
        self._provider = provider
        self._voice_id = voice_id
        self._native_sample_rate = sample_rate

    @property
    def provider_name(self) -> str:
        return self._provider.name

    @property
    def voice_id(self) -> str:
        return self._voice_id

    async def run_tts(
        self,
        text: str,
        context_id: str | None = None,
    ) -> AsyncGenerator[Frame | None, None]:
        if not text or not text.strip():
            return
        logger.debug(
            "ProviderBackedTTSService(%s) run_tts: %r",
            self._provider.name, text[:80],
        )

        yield TTSStartedFrame()
        try:
            async for chunk in self._provider.synthesize(text, voice_id=self._voice_id):
                if chunk.is_final:
                    continue  # EOS marker — TTSStoppedFrame fires in finally
                if not chunk.audio_bytes:
                    continue
                pcm = _decode_chunk_to_pcm(chunk.audio_bytes, chunk.sample_rate)
                if not pcm:
                    continue
                yield TTSAudioRawFrame(
                    audio=pcm,
                    sample_rate=chunk.sample_rate,
                    num_channels=1,
                )
        except TTSError as e:
            logger.warning(
                "ProviderBackedTTSService(%s) failed: %s", self._provider.name, e,
            )
            yield ErrorFrame(error=f"{self._provider.name} TTS failed: {e}")
        finally:
            yield TTSStoppedFrame()


def _decode_chunk_to_pcm(audio_bytes: bytes, expected_sr: int) -> bytes:
    """Decode a chunk's audio bytes into raw int16 little-endian PCM.

    F5-TTS streams complete WAV files per clause; ElevenLabs streams MP3
    bytes. We try WAV first (cheap, no external decoder), and fall back to
    soundfile for anything else (handles WAV and FLAC; MP3 requires
    libsndfile built with ffmpeg, which is the case on SOVERYN).

    Returns raw int16 LE PCM bytes ready for ``TTSAudioRawFrame``.
    """
    if not audio_bytes:
        return b""
    # WAV header sniff — fast path that avoids invoking soundfile when we
    # already know F5TTSProvider gave us a WAV chunk.
    if audio_bytes[:4] == b"RIFF" and audio_bytes[8:12] == b"WAVE":
        try:
            import soundfile as sf

            audio, sr = sf.read(io.BytesIO(audio_bytes), dtype="int16")
            if sr != expected_sr:
                logger.debug(
                    "decode_chunk: sr mismatch (got %d, expected %d) — "
                    "trusting chunk SR",
                    sr, expected_sr,
                )
            if hasattr(audio, "ndim") and audio.ndim > 1:
                # Mono-ize via channel 0; sovereign TTS is mono by contract.
                audio = audio[:, 0]
            return audio.tobytes()
        except Exception as e:  # noqa: BLE001
            logger.exception("WAV decode failed: %s", e)
            return b""
    # Non-WAV (e.g. ElevenLabs MP3): hand to soundfile which handles MP3
    # when libsndfile is built with libmpg123 / ffmpeg. On vnext both are
    # present via the conda env.
    try:
        import soundfile as sf

        audio, sr = sf.read(io.BytesIO(audio_bytes), dtype="int16")
        if hasattr(audio, "ndim") and audio.ndim > 1:
            audio = audio[:, 0]
        return audio.tobytes()
    except Exception:
        # Last-resort: treat the bytes as already-raw PCM (some legacy
        # callers do this). Better than dropping audio entirely.
        logger.debug("decode_chunk: opaque bytes, passing through as raw PCM")
        return audio_bytes


def build_tts_service(
    *,
    voice_id: str,
    elevenlabs_api_key: str | None,
    aiohttp_session: Any | None = None,
    primary: str | None = None,
    f5tts_url: str | None = None,
) -> ProviderBackedTTSService:
    """Construct the Pipecat TTSService, selecting provider via env / arg.

    Selection precedence: ``primary`` arg > ``SOVEREIGN_TTS_PRIMARY`` env
    > ``DEFAULT_PRIMARY`` (``"f5tts"``).

    ``f5tts_url`` overrides the local service URL; useful for tests.
    ``aiohttp_session`` is accepted for API parity with the previous
    ElevenLabsHttpTTSService construction shape and currently unused
    (httpx is used internally by the providers).
    """
    selection = (primary or os.environ.get("SOVEREIGN_TTS_PRIMARY") or DEFAULT_PRIMARY).lower()

    if selection == "f5tts":
        provider = F5TTSProvider(
            url=f5tts_url or os.environ.get("F5TTS_URL", F5TTS_DEFAULT_URL),
            sample_rate=F5TTS_SAMPLE_RATE,
        )
        return ProviderBackedTTSService(
            provider=provider,
            voice_id=voice_id,
            sample_rate=F5TTS_SAMPLE_RATE,
        )

    if selection == "elevenlabs":
        if not elevenlabs_api_key:
            raise ValueError(
                "SOVEREIGN_TTS_PRIMARY=elevenlabs requires elevenlabs_api_key"
            )
        provider = ElevenLabsTTSProvider(
            api_key=elevenlabs_api_key,
            sample_rate=ELEVENLABS_SAMPLE_RATE,
        )
        return ProviderBackedTTSService(
            provider=provider,
            voice_id=voice_id,
            sample_rate=ELEVENLABS_SAMPLE_RATE,
        )

    raise ValueError(
        f"unknown SOVEREIGN_TTS_PRIMARY={selection!r}; "
        "expected 'f5tts' or 'elevenlabs'"
    )


__all__ = [
    "DEFAULT_PRIMARY",
    "ProviderBackedTTSService",
    "build_tts_service",
]
