"""Pipecat-based voice pipeline factory.

Architecture (pipecat 1.3.0):

    browser mic
        |
    SmallWebRTCTransport.input()
        | AudioRawFrame
    SileroVADAnalyzer  (VAD*SpeakingFrames)
        |
    ParakeetSTTService (SegmentedSTTService subclass)
        | TranscriptionFrame
    AgentLoopBridge
        | LLMFullResponseStart/Text/End
    TTS (F5 primary / ElevenLabs fallback)
        | TTSAudioRawFrame
    FirstAudioMetricsProbe (PR1)
        |
    SmallWebRTCTransport.output()

Interruption: AgentLoopBridge handles InterruptionFrame when present.
Pipecat 1.3.0 removed PipelineParams.allow_interruptions — that kwarg is a
no-op and must not be passed. Live barge-in emission is Phase 2 (TurnController).

See: docs/designs/2026-08-16-duplex-voice-shell.md
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncGenerator
from typing import Any

import aiohttp
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    Frame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.stt_service import SegmentedSTTService
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.utils.time import time_now_iso8601
from pipecat.workers.runner import WorkerRunner

from soveryn.agents.loop import AgentLoop, TTSTokenEvent
from soveryn.platform.voice.duplex_config import DuplexConfig
from soveryn.platform.voice.metrics import TurnMetricsTracker
from soveryn.platform.voice.sanitize import sanitize_for_tts
from soveryn.platform.voice.sovereign_tts import (
    ProviderBackedTTSService,
    build_tts_service,
)

logger = logging.getLogger(__name__)


DEFAULT_PARAKEET_URL = "http://127.0.0.1:8087"
DEFAULT_SAMPLE_RATE = 16000


# --------------------------------------------------------------------------
# Custom STT — Parakeet HTTP wrapper
# --------------------------------------------------------------------------


class ParakeetSTTService(SegmentedSTTService):
    """SOVERYN Parakeet HTTP wrapper. VAD-bounded segments only.

    SegmentedSTTService handles the heavy lifting: subscribing to
    VADUserStartedSpeakingFrame / VADUserStoppedSpeakingFrame, buffering
    audio bytes, and WAV-encoding the buffer before calling run_stt().
    We override run_stt() to POST the WAV bytes to Parakeet and surface
    the resulting transcript as a TranscriptionFrame.

    Parakeet runs locally on :8087; the endpoint accepts ``POST /transcribe``
    with ``Content-Type: audio/wav`` and returns ``{"text": "..."}``.
    """

    def __init__(
        self,
        *,
        url: str = DEFAULT_PARAKEET_URL,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        aiohttp_session: aiohttp.ClientSession | None = None,
        metrics: TurnMetricsTracker | None = None,
        **kwargs: Any,
    ):
        # Pipecat's STTSettings.validate_complete() fails the pipeline at
        # startup unless model + language are explicitly set, even when the
        # upstream STT doesn't honor them (Parakeet is a single-model server).
        # The parent STTService accepts a `settings=` kwarg, NOT bare model /
        # language. Pass an STTSettings instance with both fields populated so
        # validate_complete() finds them. Service-specific routing is not
        # affected — Parakeet only sees the WAV bytes we POST.
        from pipecat.services.settings import STTSettings
        if "settings" not in kwargs:
            kwargs["settings"] = STTSettings(model="parakeet", language="en")
        super().__init__(sample_rate=sample_rate, **kwargs)
        self._url = url.rstrip("/") + "/transcribe"
        self._aiohttp_session = aiohttp_session
        self._metrics = metrics
        self.last_stt_ms: int | None = None

    @property
    def transcribe_url(self) -> str:
        """Expose the resolved POST URL for diagnostics and tests."""
        return self._url

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame | None, None]:
        if not audio:
            return
        if self._aiohttp_session is None:
            self._aiohttp_session = aiohttp.ClientSession()
        if self._metrics is not None:
            self._metrics.mark_stt_start()
        t0 = time.perf_counter()
        try:
            async with self._aiohttp_session.post(
                self._url,
                data=audio,
                headers={"Content-Type": "audio/wav"},
                timeout=aiohttp.ClientTimeout(total=10.0),
            ) as response:
                if response.status != 200:
                    logger.warning(
                        "parakeet stt non-200 (status=%s); dropping segment",
                        response.status,
                    )
                    return
                payload = await response.json()
                text = (payload.get("text") or "").strip()
                elapsed_ms = int(round((time.perf_counter() - t0) * 1000))
                self.last_stt_ms = elapsed_ms
                if self._metrics is not None:
                    self._metrics.mark_stt_end()
                if text:
                    yield TranscriptionFrame(
                        text=text,
                        user_id=getattr(self, "_user_id", "") or "",
                        timestamp=time_now_iso8601(),
                    )
        except Exception:  # noqa: BLE001 — STT outages must not crash pipeline
            logger.exception("parakeet stt call failed; dropping segment")
            return


# --------------------------------------------------------------------------
# AgentLoop bridge — FrameProcessor
# --------------------------------------------------------------------------


class AgentLoopBridge(FrameProcessor):
    """Bridges Pipecat <-> AgentLoop.process_message_stream.

    Consumes TranscriptionFrame (finalized utterance) and emits
    LLMFullResponseStartFrame -> LLMTextFrame* -> LLMFullResponseEndFrame.

    AgentLoop.process_message_stream is a SYNC generator (existing chat
    contract). We run it on a worker thread and forward its TTSTokenEvents
    onto the asyncio loop via an asyncio.Queue. Cancelling the in-flight
    asyncio task drops queued items and signals the producer thread to
    drain its inner generator (the cancellation surfaces on the next
    queue.put()).

    InterruptionFrame mid-turn: cancel the in-flight task, emit
    LLMFullResponseEndFrame so the downstream TTS service flushes cleanly,
    then propagate the frame so siblings can drop their pending audio.

    NB: we deliberately skip Pipecat's LLMContextAggregatorPair — AgentLoop
    owns all conversation state (lattice, conv_store, persona). The voice
    bridge is output-only with respect to context.
    """

    _QUEUE_SENTINEL = object()

    def __init__(
        self,
        *,
        agent_loop: AgentLoop,
        session_id: str,
        metrics: TurnMetricsTracker | None = None,
        stt: ParakeetSTTService | None = None,
    ):
        super().__init__()
        self._agent_loop = agent_loop
        self._session_id = session_id
        self._inflight_task: asyncio.Task | None = None
        self._metrics = metrics
        self._stt = stt

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, InterruptionFrame):
            if self._metrics is not None:
                self._metrics.note_cancel("interruption")
                self._metrics.finish()
            await self._cancel_inflight()
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, TranscriptionFrame):
            text = (frame.text or "").strip()
            if text:
                await self._cancel_inflight()
                stt_ms = self._stt.last_stt_ms if self._stt is not None else None
                if self._metrics is not None:
                    self._metrics.begin_user_turn(text, stt_ms=stt_ms)
                self._inflight_task = asyncio.create_task(self._run_turn(text))
            return

        await self.push_frame(frame, direction)

    async def _cancel_inflight(self) -> None:
        if self._inflight_task is None or self._inflight_task.done():
            self._inflight_task = None
            return
        self._inflight_task.cancel()
        try:
            await self._inflight_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        self._inflight_task = None

    async def _run_turn(self, user_text: str) -> None:
        """Run one AgentLoop turn, streaming TTSTokenEvents into LLMTextFrames.

        Always emits LLMFullResponseStartFrame at the start and
        LLMFullResponseEndFrame at the end (including on cancellation /
        error) so the downstream TTS service knows when to flush.
        """
        await self.push_frame(LLMFullResponseStartFrame())
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        first_token = True

        def _producer() -> None:
            pending_tts = ""

            def _flush_pending() -> None:
                nonlocal pending_tts
                if pending_tts.strip():
                    loop.call_soon_threadsafe(queue.put_nowait, pending_tts)
                pending_tts = ""

            try:
                for event in self._agent_loop.process_message_stream(
                    self._session_id, user_text,
                ):
                    if isinstance(event, TTSTokenEvent):
                        # Already sanitized at source; re-sanitize is a cheap
                        # idempotent safety net in case a future code path
                        # emits a raw chunk. We then buffer tiny pieces into
                        # phrase-sized chunks so the TTS service does not get
                        # one-character requests.
                        chunk = sanitize_for_tts(event.text, preserve_outer_whitespace=True)
                        if not chunk.strip():
                            continue
                        pending_tts += chunk
                        # Flush at sentence boundaries OR at a buffer threshold
                        # large enough for prosody coherence. The previous
                        # `len >= 4` flush was firing on essentially every
                        # token, which combined with TTS TOKEN-mode aggregation
                        # produced ~13 ElevenLabs API calls per short reply.
                        # SENTENCE-level TTS aggregation downstream makes this
                        # less critical, but a larger bridge buffer still
                        # reduces frame thrash.
                        if (
                            chunk.rstrip()[-1] in ".!?;:"
                            or len(pending_tts.strip()) >= 40
                        ):
                            _flush_pending()
            except Exception as exc:  # noqa: BLE001
                logger.exception("agent_loop bridge producer failed: %s", exc)
            finally:
                _flush_pending()
                loop.call_soon_threadsafe(queue.put_nowait, self._QUEUE_SENTINEL)

        producer_task = asyncio.create_task(asyncio.to_thread(_producer))
        try:
            while True:
                item = await queue.get()
                if item is self._QUEUE_SENTINEL:
                    break
                if self._metrics is not None:
                    if first_token:
                        self._metrics.mark_llm_first_token(item)
                        first_token = False
                    else:
                        self._metrics.note_assistant_chars(item)
                await self.push_frame(LLMTextFrame(text=item))
        except asyncio.CancelledError:
            # Drain queue silently; producer thread will hit the sentinel on
            # its next iteration (or has already finished). We don't join the
            # thread — call_soon_threadsafe is non-blocking either way.
            if self._metrics is not None:
                self._metrics.note_cancel("llm_cancelled")
                self._metrics.finish()
            raise
        finally:
            # Best-effort: wait for the producer task so cancellation is
            # observable. If it's still running (sync iterator blocked on a
            # network call), we let it complete naturally — the next chunk
            # it produces lands on a dead queue but won't crash the pipeline.
            if not producer_task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(producer_task), timeout=0.001)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass
            await self.push_frame(LLMFullResponseEndFrame())
            # Do not finish metrics here — wait for first TTS audio (probe) so
            # e2e_first_audio_ms is populated. Orphan turns flush on next turn
            # / disconnect / cancel.


# --------------------------------------------------------------------------
# First-audio metrics probe (after TTS)
# --------------------------------------------------------------------------


class FirstAudioMetricsProbe(FrameProcessor):
    """Marks first TTSAudioRawFrame of a turn for e2e / tts_first_audio metrics."""

    def __init__(self, metrics: TurnMetricsTracker | None = None):
        super().__init__()
        self._metrics = metrics

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if (
            self._metrics is not None
            and isinstance(frame, TTSAudioRawFrame)
            and direction == FrameDirection.DOWNSTREAM
            and self._metrics.has_open_turn()
        ):
            # First audio of turn closes the metric row (includes e2e).
            if self._metrics.mark_tts_first_audio():
                self._metrics.finish()
        await self.push_frame(frame, direction)


# --------------------------------------------------------------------------
# Pipeline factory
# --------------------------------------------------------------------------


def build_aetheria_voice_pipeline(
    *,
    agent_loop: AgentLoop,
    agent_name: str,
    voice_id: str,
    parakeet_url: str,
    elevenlabs_api_key: str,
    session_id: str,
    webrtc_connection: SmallWebRTCConnection,
    aiohttp_session: aiohttp.ClientSession | None = None,
    duplex: DuplexConfig | None = None,
) -> tuple[Pipeline, PipelineWorker]:
    """Construct the Pipecat pipeline for one Aetheria voice session.

    Returns (pipeline, worker) — caller drives the worker via WorkerRunner
    (see run_aetheria_voice_session below for the canonical run pattern).

    Component order, downstream:
        transport.input() -> VAD -> stt -> bridge -> tts -> first_audio_probe
        -> transport.output()
    """
    if aiohttp_session is None:
        aiohttp_session = aiohttp.ClientSession()

    duplex = duplex or DuplexConfig.from_env()
    metrics: TurnMetricsTracker | None = None
    if duplex.metrics_enabled:
        metrics = TurnMetricsTracker(
            agent=agent_name,
            session_id=session_id,
            adapter=duplex.adapter,
            enabled=True,
        )

    vad_analyzer = SileroVADAnalyzer(
        sample_rate=DEFAULT_SAMPLE_RATE,
        params=VADParams(
            confidence=duplex.confidence,
            start_secs=duplex.start_secs,
            stop_secs=duplex.stop_secs,
        ),
    )

    transport = SmallWebRTCTransport(
        webrtc_connection=webrtc_connection,
        params=TransportParams(
            audio_in_enabled=True,
            # Browser sends Opus at 48kHz; SileroVADAnalyzer only handles
            # 8000 or 16000 Hz. Pipe Pipecat to resample to 16kHz at the
            # transport input boundary so VAD sees the right rate. Without
            # this, audio reaches the pipeline at 48kHz, Silero silently
            # produces no voice activations, and nothing downstream fires.
            audio_in_sample_rate=DEFAULT_SAMPLE_RATE,
            audio_out_enabled=True,
            audio_out_10ms_chunks=1,
        ),
    )

    stt = ParakeetSTTService(
        url=parakeet_url,
        sample_rate=DEFAULT_SAMPLE_RATE,
        aiohttp_session=aiohttp_session,
        metrics=metrics,
    )

    bridge = AgentLoopBridge(
        agent_loop=agent_loop,
        session_id=session_id,
        metrics=metrics,
        stt=stt,
    )

    # TTS provider is selected via SOVEREIGN_TTS_PRIMARY (default "f5tts",
    # local F5-TTS on :8088). Set SOVEREIGN_TTS_PRIMARY=elevenlabs to roll
    # back to the cloud provider without touching code. The wrapper handles
    # sample-rate negotiation; both paths emit TTSAudioRawFrame downstream.
    tts = build_tts_service(
        agent_name=agent_name,
        elevenlabs_voice_id=voice_id,
        elevenlabs_api_key=elevenlabs_api_key,
        aiohttp_session=aiohttp_session,
    )

    first_audio = FirstAudioMetricsProbe(metrics=metrics)

    pipeline = Pipeline([
        transport.input(),
        VADProcessor(vad_analyzer=vad_analyzer),
        stt,
        bridge,
        tts,
        first_audio,
        transport.output(),
    ])

    # Pipecat 1.3.0: do NOT pass allow_interruptions — field removed; was a silent no-op.
    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
        ),
    )

    @transport.event_handler("on_client_disconnected")
    async def on_disconnected(t, client):  # pragma: no cover — exercised live
        if metrics is not None:
            metrics.note_cancel("client_disconnect")
            metrics.finish()
        await worker.cancel()

    return pipeline, worker


async def run_aetheria_voice_session(
    *,
    webrtc_connection: SmallWebRTCConnection,
    agent_loop: AgentLoop,
    agent_name: str,
    session_id: str,
    elevenlabs_api_key: str,
    voice_id: str,
    parakeet_url: str = DEFAULT_PARAKEET_URL,
    aiohttp_session: aiohttp.ClientSession | None = None,
    duplex: DuplexConfig | None = None,
) -> None:
    """Run one voice session end-to-end. Returns when the client disconnects.

    Called from the /voice/<agent>/offer endpoint after
    SmallWebRTCRequestHandler hands us a connection. Builds the pipeline +
    worker, hands them to WorkerRunner, and awaits run() until the worker
    cancels (on client disconnect).
    """
    _, worker = build_aetheria_voice_pipeline(
        agent_loop=agent_loop,
        agent_name=agent_name,
        voice_id=voice_id,
        parakeet_url=parakeet_url,
        elevenlabs_api_key=elevenlabs_api_key,
        session_id=session_id,
        webrtc_connection=webrtc_connection,
        aiohttp_session=aiohttp_session,
        duplex=duplex,
    )
    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    await runner.run()


__all__ = [
    "AgentLoopBridge",
    "DEFAULT_PARAKEET_URL",
    "DEFAULT_SAMPLE_RATE",
    "DuplexConfig",
    "FirstAudioMetricsProbe",
    "ParakeetSTTService",
    "TurnMetricsTracker",
    "build_aetheria_voice_pipeline",
    "run_aetheria_voice_session",
]
