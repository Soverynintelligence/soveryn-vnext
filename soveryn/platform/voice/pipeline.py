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
    TTS (Kokoro primary / F5 leftover / ElevenLabs fallback)
        | TTSAudioRawFrame
    FirstAudioMetricsProbe (PR1)
        |
    SmallWebRTCTransport.output()

Interruption: AgentLoopBridge handles InterruptionFrame when present.
Pipecat 1.3.0 removed PipelineParams.allow_interruptions — that kwarg is a
no-op and must not be passed. Live barge-in emission is Phase 2
(TurnController, PR4a — flag SOVERYN_VOICE_BARGE_IN, default off).

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

from soveryn.platform.voice.adapters.agent_loop import AgentLoopAdapter
from soveryn.platform.voice.adapters.base import AgentAdapter
from soveryn.platform.voice.duplex_config import DuplexConfig
from soveryn.platform.voice.metrics import TurnMetricsTracker
from soveryn.platform.voice.sovereign_tts import (
    ProviderBackedTTSService,
    build_tts_service,
)
from soveryn.platform.voice.turn_controller import TurnController

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
        self._turn_metrics = metrics
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
        if self._turn_metrics is not None:
            self._turn_metrics.mark_stt_start()
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
                if self._turn_metrics is not None:
                    self._turn_metrics.mark_stt_end()
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
# Agent adapter bridge — FrameProcessor
# --------------------------------------------------------------------------


class AgentAdapterBridge(FrameProcessor):
    """Bridges Pipecat <-> AgentAdapter (text brain).

    Consumes TranscriptionFrame and emits
    LLMFullResponseStartFrame -> LLMTextFrame* -> LLMFullResponseEndFrame.

    Sole owner of turn_epoch for PR4a barge-in drop (bumped via begin_interrupt).
    """

    def __init__(
        self,
        *,
        adapter: AgentAdapter,
        session_id: str,
        metrics: TurnMetricsTracker | None = None,
        stt: ParakeetSTTService | None = None,
    ):
        super().__init__()
        self._adapter = adapter
        self._session_id = session_id
        self._inflight_task: asyncio.Task | None = None
        self._cancel_event: asyncio.Event | None = None
        self._turn_metrics = metrics
        self._stt = stt
        self.turn_epoch = 0

    # Back-compat for tests that inspected AgentLoopBridge._agent_loop
    @property
    def _agent_loop(self):
        return getattr(self._adapter, "_agent_loop", None)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, InterruptionFrame):
            # TurnController may already have called begin_interrupt; keep
            # idempotent so broadcast_interruption does not double-bump epoch.
            await self.begin_interrupt(reason="interruption")
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, TranscriptionFrame):
            text = (frame.text or "").strip()
            if text:
                await self._cancel_inflight()
                stt_ms = self._stt.last_stt_ms if self._stt is not None else None
                # New user turn — bump epoch so late tokens from prior turn drop.
                self.turn_epoch += 1
                if self._turn_metrics is not None:
                    self._turn_metrics.turn_epoch = self.turn_epoch
                    self._turn_metrics.begin_user_turn(text, stt_ms=stt_ms)
                self._inflight_task = asyncio.create_task(self._run_turn(text))
            return

        await self.push_frame(frame, direction)

    async def begin_interrupt(self, *, reason: str = "barge_in") -> None:
        """Sole epoch owner: bump turn_epoch, cancel in-flight, notify adapter.

        Idempotent while an interrupt is already in flight for this turn.
        """
        if self._cancel_event is not None and self._cancel_event.is_set():
            # Already cancelled this turn's producer; still ensure task is gone.
            await self._cancel_inflight()
            return
        self.turn_epoch += 1
        if self._turn_metrics is not None:
            if reason == "barge_in":
                self._turn_metrics.note_barge_in(reason)
            else:
                self._turn_metrics.note_cancel(reason)
            self._turn_metrics.turn_epoch = self.turn_epoch
            self._turn_metrics.finish()
        if self._cancel_event is not None:
            self._cancel_event.set()
        await self._cancel_inflight()
        try:
            await self._adapter.on_cancelled(
                session_id=self._session_id,
                reason=reason,
                turn_epoch=self.turn_epoch,
            )
        except Exception:  # noqa: BLE001
            logger.exception("adapter on_cancelled failed")

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
        await self.push_frame(LLMFullResponseStartFrame())
        cancel_event = asyncio.Event()
        self._cancel_event = cancel_event
        epoch = self.turn_epoch
        first_token = True
        try:
            async for chunk in self._adapter.start_turn(
                session_id=self._session_id,
                user_text=user_text,
                cancel_event=cancel_event,
                turn_epoch=epoch,
            ):
                if cancel_event.is_set() or epoch != self.turn_epoch:
                    break
                text = chunk.text or ""
                if not text.strip():
                    continue
                if self._turn_metrics is not None:
                    if first_token:
                        self._turn_metrics.mark_llm_first_token(text)
                        first_token = False
                    else:
                        self._turn_metrics.note_assistant_chars(text)
                await self.push_frame(LLMTextFrame(text=text))
        except asyncio.CancelledError:
            if self._turn_metrics is not None:
                self._turn_metrics.note_cancel("llm_cancelled")
                self._turn_metrics.finish()
            raise
        finally:
            self._cancel_event = None
            await self.push_frame(LLMFullResponseEndFrame())


class AgentLoopBridge(AgentAdapterBridge):
    """Back-compat constructor wrapping AgentLoop in AgentLoopAdapter."""

    def __init__(
        self,
        *,
        agent_loop,  # AgentLoop — untyped to avoid import cycle in type checkers
        session_id: str,
        metrics: TurnMetricsTracker | None = None,
        stt: ParakeetSTTService | None = None,
        agent_name: str = "aetheria",
        voice_id: str | None = None,
        flush_chars: int = 40,
        tts_agg: str = "sentence",
    ):
        adapter = AgentLoopAdapter(
            agent_loop,
            agent_id=agent_name,
            voice_id=voice_id or agent_name,
            flush_chars=flush_chars,
            tts_agg=tts_agg,
        )
        super().__init__(
            adapter=adapter,
            session_id=session_id,
            metrics=metrics,
            stt=stt,
        )


# --------------------------------------------------------------------------
# First-audio metrics probe (after TTS)
# --------------------------------------------------------------------------


class FirstAudioMetricsProbe(FrameProcessor):
    """Marks first TTSAudioRawFrame of a turn for e2e / tts_first_audio metrics."""

    def __init__(self, metrics: TurnMetricsTracker | None = None):
        super().__init__()
        self._turn_metrics = metrics

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if (
            self._turn_metrics is not None
            and isinstance(frame, TTSAudioRawFrame)
            and direction == FrameDirection.DOWNSTREAM
            and self._turn_metrics.has_open_turn()
        ):
            # First audio of turn closes the metric row (includes e2e).
            if self._turn_metrics.mark_tts_first_audio():
                self._turn_metrics.finish()
        await self.push_frame(frame, direction)


# --------------------------------------------------------------------------
# Pipeline factory
# --------------------------------------------------------------------------


def build_voice_pipeline(
    *,
    adapter: AgentAdapter,
    session_id: str,
    webrtc_connection: SmallWebRTCConnection,
    parakeet_url: str = DEFAULT_PARAKEET_URL,
    duplex: DuplexConfig | None = None,
    elevenlabs_api_key: str | None = None,
    elevenlabs_voice_id: str | None = None,
    aiohttp_session: aiohttp.ClientSession | None = None,
) -> tuple[Pipeline, PipelineWorker]:
    """Construct the Pipecat pipeline for one voice session (any AgentAdapter).

    Component order, downstream:
        transport.input() -> VAD -> stt -> bridge -> tts -> first_audio_probe
        -> transport.output()

    Kokoro maps ``adapter.agent_id`` to a local voice (Aetheria →
    ``af_heart``). F5-TTS uses the agent id as the voice registry key.
    ElevenLabs keys are optional when primary is kokoro or f5tts.
    """
    if aiohttp_session is None:
        aiohttp_session = aiohttp.ClientSession()

    duplex = duplex or DuplexConfig.from_env()
    metrics: TurnMetricsTracker | None = None
    if duplex.metrics_enabled:
        metrics = TurnMetricsTracker(
            agent=adapter.agent_id,
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

    # TurnController before STT so it sees VAD frames; bot_* arrives UPSTREAM
    # from transport.output. Bridge is bound after construction.
    turn_controller = TurnController(duplex=duplex, bridge=None)

    bridge = AgentAdapterBridge(
        adapter=adapter,
        session_id=session_id,
        metrics=metrics,
        stt=stt,
    )
    turn_controller.bind_bridge(bridge)

    tts = build_tts_service(
        agent_name=adapter.agent_id,
        elevenlabs_voice_id=elevenlabs_voice_id or adapter.voice_id,
        elevenlabs_api_key=elevenlabs_api_key,
        aiohttp_session=aiohttp_session,
        tts_agg=duplex.tts_agg,
    )

    first_audio = FirstAudioMetricsProbe(metrics=metrics)

    # Order: VAD → TurnController → STT → bridge → TTS → probe → out
    pipeline = Pipeline([
        transport.input(),
        VADProcessor(vad_analyzer=vad_analyzer),
        turn_controller,
        stt,
        bridge,
        tts,
        first_audio,
        transport.output(),
    ])

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
        try:
            await adapter.on_session_end(session_id=session_id)
        except Exception:  # noqa: BLE001
            logger.exception("adapter on_session_end failed")
        await worker.cancel()

    return pipeline, worker


def _f5_safe_adapter_agg(duplex: DuplexConfig) -> tuple[str, int]:
    """Local synth (Kokoro / F5) — TOKEN bridge flush chops playout. Force sentence."""
    import os

    primary = (os.environ.get("SOVEREIGN_TTS_PRIMARY") or "f5tts").strip().lower()
    tts_agg = duplex.tts_agg
    flush = duplex.bridge_flush_chars
    if primary in ("f5tts", "kokoro") and tts_agg == "token":
        logger.info(
            "%s: coercing adapter tts_agg token→sentence (avoids choppy speech)",
            primary,
        )
        return "sentence", max(flush, 40)
    return tts_agg, flush


def build_aetheria_voice_pipeline(
    *,
    agent_loop,  # AgentLoop
    agent_name: str,
    voice_id: str | None,
    parakeet_url: str,
    elevenlabs_api_key: str | None,
    session_id: str,
    webrtc_connection: SmallWebRTCConnection,
    aiohttp_session: aiohttp.ClientSession | None = None,
    duplex: DuplexConfig | None = None,
) -> tuple[Pipeline, PipelineWorker]:
    """Thin wrapper: AgentLoopAdapter + build_voice_pipeline (PR2)."""
    duplex = duplex or DuplexConfig.from_env()
    tts_agg, flush_chars = _f5_safe_adapter_agg(duplex)
    adapter = AgentLoopAdapter(
        agent_loop,
        agent_id=agent_name,
        voice_id=voice_id or agent_name,
        flush_chars=flush_chars,
        tts_agg=tts_agg,
    )
    return build_voice_pipeline(
        adapter=adapter,
        session_id=session_id,
        webrtc_connection=webrtc_connection,
        parakeet_url=parakeet_url,
        duplex=duplex,
        elevenlabs_api_key=elevenlabs_api_key,
        elevenlabs_voice_id=voice_id,
        aiohttp_session=aiohttp_session,
    )


async def run_voice_session(
    *,
    webrtc_connection: SmallWebRTCConnection,
    adapter: AgentAdapter,
    session_id: str,
    parakeet_url: str = DEFAULT_PARAKEET_URL,
    elevenlabs_api_key: str | None = None,
    elevenlabs_voice_id: str | None = None,
    aiohttp_session: aiohttp.ClientSession | None = None,
    duplex: DuplexConfig | None = None,
) -> None:
    """Run one voice session for any adapter until client disconnect."""
    _, worker = build_voice_pipeline(
        adapter=adapter,
        session_id=session_id,
        webrtc_connection=webrtc_connection,
        parakeet_url=parakeet_url,
        duplex=duplex,
        elevenlabs_api_key=elevenlabs_api_key,
        elevenlabs_voice_id=elevenlabs_voice_id,
        aiohttp_session=aiohttp_session,
    )
    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    await runner.run()


async def run_aetheria_voice_session(
    *,
    webrtc_connection: SmallWebRTCConnection,
    agent_loop,  # AgentLoop
    agent_name: str,
    session_id: str,
    elevenlabs_api_key: str | None,
    voice_id: str | None,
    parakeet_url: str = DEFAULT_PARAKEET_URL,
    aiohttp_session: aiohttp.ClientSession | None = None,
    duplex: DuplexConfig | None = None,
) -> None:
    """Run one AgentLoop voice session (wrapper for dispatch compat)."""
    duplex = duplex or DuplexConfig.from_env()
    tts_agg, flush_chars = _f5_safe_adapter_agg(duplex)
    adapter = AgentLoopAdapter(
        agent_loop,
        agent_id=agent_name,
        voice_id=voice_id or agent_name,
        flush_chars=flush_chars,
        tts_agg=tts_agg,
    )
    await run_voice_session(
        webrtc_connection=webrtc_connection,
        adapter=adapter,
        session_id=session_id,
        parakeet_url=parakeet_url,
        elevenlabs_api_key=elevenlabs_api_key,
        elevenlabs_voice_id=voice_id,
        aiohttp_session=aiohttp_session,
        duplex=duplex,
    )


__all__ = [
    "AgentAdapterBridge",
    "AgentLoopBridge",
    "DEFAULT_PARAKEET_URL",
    "DEFAULT_SAMPLE_RATE",
    "DuplexConfig",
    "FirstAudioMetricsProbe",
    "ParakeetSTTService",
    "TurnController",
    "TurnMetricsTracker",
    "build_aetheria_voice_pipeline",
    "build_voice_pipeline",
    "run_aetheria_voice_session",
    "run_voice_session",
]
