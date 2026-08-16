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

import asyncio
import io
import logging
import os
from collections.abc import AsyncGenerator
from typing import Any

from pipecat.frames.frames import (
    ErrorFrame,
    Frame,
    InterruptionFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.tts_service import TTSService, TextAggregationMode

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
        text_aggregation_mode: TextAggregationMode | None = None,
        **kwargs: Any,
    ) -> None:
        # Explicit aggregation mode. Default SENTENCE — F5 is clause/HTTP and
        # TOKEN fragments sound broken. TOKEN via SOVERYN_VOICE_TTS_AGG for
        # streaming providers.
        if text_aggregation_mode is None:
            text_aggregation_mode = TextAggregationMode.SENTENCE
        super().__init__(
            sample_rate=sample_rate,
            text_aggregation_mode=text_aggregation_mode,
            **kwargs,
        )
        self._provider = provider
        self._voice_id = voice_id
        self._native_sample_rate = sample_rate
        self._text_aggregation_mode = text_aggregation_mode
        # PR4b: set on InterruptionFrame so F5 stream acloses and stops PCM.
        self._cancel_event = asyncio.Event()
        self.last_f5_clauses_after_cancel: int | None = None

    @property
    def provider_name(self) -> str:
        return self._provider.name

    @property
    def voice_id(self) -> str:
        return self._voice_id

    @property
    def text_aggregation_mode(self) -> TextAggregationMode:
        return self._text_aggregation_mode

    async def _handle_interruption(
        self, frame: InterruptionFrame, direction: FrameDirection
    ) -> None:
        """Abort in-flight provider stream, then Pipecat's queue drop."""
        self._cancel_event.set()
        abort = getattr(self._provider, "abort", None)
        if abort is not None:
            try:
                await abort()
            except Exception:  # noqa: BLE001
                logger.exception(
                    "ProviderBackedTTSService(%s) abort failed",
                    self._provider.name,
                )
        after = getattr(self._provider, "clauses_completed_after_cancel", None)
        if isinstance(after, int) and after > 0:
            self.last_f5_clauses_after_cancel = after
            logger.info(
                "F5 clauses completed after cancel=%s (playout dropped them)",
                after,
            )
        await super()._handle_interruption(frame, direction)

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

        # Fresh cancel gate per utterance; interruptions set it.
        self._cancel_event = asyncio.Event()
        self.last_f5_clauses_after_cancel = None

        yield TTSStartedFrame()
        try:
            # Prefer cancel_event when provider supports it (F5 PR4b).
            try:
                stream = self._provider.synthesize(
                    text,
                    voice_id=self._voice_id,
                    cancel_event=self._cancel_event,
                )
            except TypeError:
                stream = self._provider.synthesize(
                    text, voice_id=self._voice_id
                )
            async for chunk in stream:
                if self._cancel_event.is_set():
                    break
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
        except asyncio.CancelledError:
            self._cancel_event.set()
            abort = getattr(self._provider, "abort", None)
            if abort is not None:
                await abort()
            raise
        except TTSError as e:
            if self._cancel_event.is_set():
                logger.debug(
                    "ProviderBackedTTSService(%s) ended after cancel: %s",
                    self._provider.name, e,
                )
            else:
                logger.warning(
                    "ProviderBackedTTSService(%s) failed: %s",
                    self._provider.name, e,
                )
                yield ErrorFrame(error=f"{self._provider.name} TTS failed: {e}")
        finally:
            after = getattr(self._provider, "clauses_completed_after_cancel", None)
            if isinstance(after, int) and after > 0:
                self.last_f5_clauses_after_cancel = after
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


def resolve_text_aggregation_mode(
    tts_agg: str | TextAggregationMode | None = None,
) -> TextAggregationMode:
    """Map DuplexConfig / env string to Pipecat TextAggregationMode.

    Default is SENTENCE (safe for F5 clause synthesis).
    """
    if isinstance(tts_agg, TextAggregationMode):
        return tts_agg
    raw = (tts_agg or os.environ.get("SOVERYN_VOICE_TTS_AGG") or "sentence").strip().lower()
    if raw in ("token", "tok"):
        return TextAggregationMode.TOKEN
    return TextAggregationMode.SENTENCE


def build_tts_service(
    *,
    agent_name: str,
    elevenlabs_voice_id: str | None,
    elevenlabs_api_key: str | None,
    aiohttp_session: Any | None = None,
    primary: str | None = None,
    f5tts_url: str | None = None,
    tts_agg: str | TextAggregationMode | None = None,
) -> ProviderBackedTTSService:
    """Construct the Pipecat TTSService, selecting provider via env / arg.

    Selection precedence: ``primary`` arg > ``SOVEREIGN_TTS_PRIMARY`` env
    > ``DEFAULT_PRIMARY`` (``"f5tts"``).

    ``agent_name`` is the registry key the local F5-TTS service keys on
    (e.g. ``"aetheria"``); ``elevenlabs_voice_id`` is the cloud UUID for
    the fallback provider. Each provider gets the voice_id shape it expects.

    ``tts_agg`` / ``SOVERYN_VOICE_TTS_AGG``: ``sentence`` (default — whole
    clauses for F5) or ``token`` (streaming providers / latency experiments).
    **F5 always uses SENTENCE**: token fragments create choppy playout
    because each fragment is a full HTTP synthesize with its own prosody.

    ``f5tts_url`` overrides the local service URL; useful for tests.
    ``aiohttp_session`` is accepted for API parity with the previous
    ElevenLabsHttpTTSService construction shape and currently unused
    (httpx is used internally by the providers).
    """
    selection = (primary or os.environ.get("SOVEREIGN_TTS_PRIMARY") or DEFAULT_PRIMARY).lower()
    agg_mode = resolve_text_aggregation_mode(tts_agg)

    if selection == "f5tts":
        if agg_mode == TextAggregationMode.TOKEN:
            logger.info(
                "F5-TTS ignores TOKEN aggregation (clause HTTP synth); using SENTENCE"
            )
            agg_mode = TextAggregationMode.SENTENCE
        provider = F5TTSProvider(
            url=f5tts_url or os.environ.get("F5TTS_URL", F5TTS_DEFAULT_URL),
            sample_rate=F5TTS_SAMPLE_RATE,
        )
        return ProviderBackedTTSService(
            provider=provider,
            voice_id=agent_name,
            sample_rate=F5TTS_SAMPLE_RATE,
            text_aggregation_mode=agg_mode,
        )

    if selection == "elevenlabs":
        if not elevenlabs_api_key or not elevenlabs_voice_id:
            raise ValueError(
                "SOVEREIGN_TTS_PRIMARY=elevenlabs requires elevenlabs_api_key + elevenlabs_voice_id"
            )
        provider = ElevenLabsTTSProvider(
            api_key=elevenlabs_api_key,
            sample_rate=ELEVENLABS_SAMPLE_RATE,
        )
        return ProviderBackedTTSService(
            provider=provider,
            voice_id=elevenlabs_voice_id,
            sample_rate=ELEVENLABS_SAMPLE_RATE,
            text_aggregation_mode=agg_mode,
        )

    raise ValueError(
        f"unknown SOVEREIGN_TTS_PRIMARY={selection!r}; "
        "expected 'f5tts' or 'elevenlabs'"
    )


__all__ = [
    "DEFAULT_PRIMARY",
    "ProviderBackedTTSService",
    "TextAggregationMode",
    "build_tts_service",
    "resolve_text_aggregation_mode",
]
