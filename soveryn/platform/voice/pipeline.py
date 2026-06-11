"""Pipecat-based voice pipeline factory — Phase 1 (Aetheria, ElevenLabs).

Architecture (verified via pipecat 1.3.0 spike, 2026-06-10):

    browser mic
        |
    SmallWebRTCTransport.input()
        | AudioRawFrame
    SileroVADAnalyzer  (in TransportParams, emits VAD*SpeakingFrames)
        |
    ParakeetSTTService (SegmentedSTTService subclass)
        | TranscriptionFrame (finalized=True)
    AgentLoopBridge   (plain FrameProcessor — NOT an LLMService subclass)
        | LLMFullResponseStartFrame, LLMTextFrame*, LLMFullResponseEndFrame
    ElevenLabsHttpTTSService  (Pipecat built-in)
        | TTSAudioRawFrame
    SmallWebRTCTransport.output()
        |
    browser speakers

Interruption: when SileroVAD detects user speech mid-bot-talk, the transport
emits InterruptionFrame downstream. AgentLoopBridge cancels its in-flight
AgentLoop generator; TTS drops pending audio.

AgentLoop.process_message_stream is a sync generator; the bridge runs it on
a worker thread and bridges its TTSTokenEvents back onto the asyncio loop
via an asyncio.Queue. This keeps the cancel-on-InterruptionFrame contract
clean (cancel the queue-drain task; the producer thread shuts down on the
next iteration via a sentinel).

See: docs/superpowers/notes/2026-06-10-pipecat-spike.md (Section 10 for the
canonical skeleton this file fills in).
"""

from __future__ import annotations

import asyncio
import logging
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
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.elevenlabs.tts import ElevenLabsHttpTTSService
from pipecat.services.stt_service import SegmentedSTTService
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.utils.time import time_now_iso8601
from pipecat.workers.runner import WorkerRunner

from soveryn.agents.loop import AgentLoop, TTSTokenEvent
from soveryn.platform.voice.sanitize import sanitize_for_tts

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

    @property
    def transcribe_url(self) -> str:
        """Expose the resolved POST URL for diagnostics and tests."""
        return self._url

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame | None, None]:
        if not audio:
            return
        if self._aiohttp_session is None:
            self._aiohttp_session = aiohttp.ClientSession()
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

    def __init__(self, *, agent_loop: AgentLoop, session_id: str):
        super().__init__()
        self._agent_loop = agent_loop
        self._session_id = session_id
        self._inflight_task: asyncio.Task | None = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, InterruptionFrame):
            await self._cancel_inflight()
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, TranscriptionFrame):
            text = (frame.text or "").strip()
            if text:
                await self._cancel_inflight()
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

        def _producer() -> None:
            try:
                for event in self._agent_loop.process_message_stream(
                    self._session_id, user_text,
                ):
                    if isinstance(event, TTSTokenEvent):
                        # Already sanitized at source; re-sanitize is a cheap
                        # idempotent safety net in case a future code path
                        # emits a raw chunk.
                        chunk = sanitize_for_tts(event.text, preserve_outer_whitespace=True)
                        if chunk.strip():
                            loop.call_soon_threadsafe(queue.put_nowait, chunk)
            except Exception as exc:  # noqa: BLE001
                logger.exception("agent_loop bridge producer failed: %s", exc)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, self._QUEUE_SENTINEL)

        producer_task = asyncio.create_task(asyncio.to_thread(_producer))
        try:
            while True:
                item = await queue.get()
                if item is self._QUEUE_SENTINEL:
                    break
                await self.push_frame(LLMTextFrame(text=item))
        except asyncio.CancelledError:
            # Drain queue silently; producer thread will hit the sentinel on
            # its next iteration (or has already finished). We don't join the
            # thread — call_soon_threadsafe is non-blocking either way.
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


# --------------------------------------------------------------------------
# Pipeline factory
# --------------------------------------------------------------------------


def build_aetheria_voice_pipeline(
    *,
    agent_loop: AgentLoop,
    voice_id: str,
    parakeet_url: str,
    elevenlabs_api_key: str,
    session_id: str,
    webrtc_connection: SmallWebRTCConnection,
    aiohttp_session: aiohttp.ClientSession | None = None,
) -> tuple[Pipeline, PipelineWorker]:
    """Construct the Pipecat pipeline for one Aetheria voice session.

    Returns (pipeline, worker) — caller drives the worker via WorkerRunner
    (see run_aetheria_voice_session below for the canonical run pattern).

    Component order, downstream:
        transport.input() -> stt -> bridge -> tts -> transport.output()

    The VAD analyzer lives inside TransportParams (not as a separate
    pipeline stage) per Pipecat 1.3.0 convention; SileroVAD detects speech
    boundaries and emits VAD*SpeakingFrames the STT service consumes.

    audio_in + audio_out are enabled. The browser is expected to attach
    BOTH audio AND video transceivers — SmallWebRTCTransport requires
    both for SDP negotiation, even for voice-only sessions. The orb UI JS
    (Task 6) handles that contract on the browser side.
    """
    if aiohttp_session is None:
        aiohttp_session = aiohttp.ClientSession()

    vad_analyzer = SileroVADAnalyzer(
        sample_rate=DEFAULT_SAMPLE_RATE,
        # Lowered confidence from 0.7 → 0.3 and start_secs 0.2 → 0.1
        # as diagnostic — if nothing fires at this level, audio isn't
        # reaching Silero at all; if voice fires, threshold was too
        # restrictive. Tune back up after we confirm audio path.
        params=VADParams(confidence=0.3, start_secs=0.1, stop_secs=0.3),
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
            audio_out_10ms_chunks=2,
        ),
    )

    stt = ParakeetSTTService(
        url=parakeet_url,
        sample_rate=DEFAULT_SAMPLE_RATE,
        aiohttp_session=aiohttp_session,
    )

    bridge = AgentLoopBridge(agent_loop=agent_loop, session_id=session_id)

    # Pipecat 1.3.0 moved voice selection into a Settings object; the bare
    # voice_id kwarg still works but emits a DeprecationWarning. Use the
    # current shape so we're not starting on a deprecated symbol.
    tts = ElevenLabsHttpTTSService(
        api_key=elevenlabs_api_key,
        aiohttp_session=aiohttp_session,
        settings=ElevenLabsHttpTTSService.Settings(voice=voice_id),
    )

    pipeline = Pipeline([
        transport.input(),
        VADProcessor(vad_analyzer=vad_analyzer),
        stt,
        bridge,
        tts,
        transport.output(),
    ])

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            enable_metrics=True,
        ),
    )

    @transport.event_handler("on_client_disconnected")
    async def on_disconnected(t, client):  # pragma: no cover — exercised live
        await worker.cancel()

    return pipeline, worker


async def run_aetheria_voice_session(
    *,
    webrtc_connection: SmallWebRTCConnection,
    agent_loop: AgentLoop,
    session_id: str,
    elevenlabs_api_key: str,
    voice_id: str,
    parakeet_url: str = DEFAULT_PARAKEET_URL,
    aiohttp_session: aiohttp.ClientSession | None = None,
) -> None:
    """Run one voice session end-to-end. Returns when the client disconnects.

    Called from the /voice/<agent>/offer endpoint after
    SmallWebRTCRequestHandler hands us a connection. Builds the pipeline +
    worker, hands them to WorkerRunner, and awaits run() until the worker
    cancels (on client disconnect).
    """
    _, worker = build_aetheria_voice_pipeline(
        agent_loop=agent_loop,
        voice_id=voice_id,
        parakeet_url=parakeet_url,
        elevenlabs_api_key=elevenlabs_api_key,
        session_id=session_id,
        webrtc_connection=webrtc_connection,
        aiohttp_session=aiohttp_session,
    )
    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    await runner.run()


__all__ = [
    "AgentLoopBridge",
    "DEFAULT_PARAKEET_URL",
    "DEFAULT_SAMPLE_RATE",
    "ParakeetSTTService",
    "build_aetheria_voice_pipeline",
    "run_aetheria_voice_session",
]
