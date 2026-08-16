"""Smoke tests for soveryn.platform.voice.pipeline.

Verify factory wiring and bridge behavior at the unit level. Live WebRTC
round-trip is verified manually in Task 8 — the smoke tests here only
exercise:

  - the pipeline factory constructs all expected processors and returns a
    PipelineWorker
  - ParakeetSTTService POSTs to the configured URL with WAV body
  - AgentLoopBridge consumes TTSTokenEvents and emits LLMTextFrames via
    push_frame (tested by stubbing push_frame so we don't need to spin up
    a full Pipecat TaskManager / PipelineWorker for the assertion)
  - AgentLoopBridge cancels in-flight work on InterruptionFrame and emits
    a closing LLMFullResponseEndFrame

pytest-asyncio isn't installed in this env, so async test bodies use
``asyncio.run(...)`` from sync test functions (mirrors the pattern in
tests/test_voice_elevenlabs_provider.py).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from unittest.mock import patch

from pipecat.frames.frames import (
    Frame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TranscriptionFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineWorker
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.stt_service import SegmentedSTTService
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection

from soveryn.agents.loop import TTSTokenEvent
from soveryn.platform.voice.pipeline import (
    AgentLoopBridge,
    DEFAULT_PARAKEET_URL,
    ParakeetSTTService,
    build_aetheria_voice_pipeline,
)
from soveryn.platform.voice.sovereign_tts import ProviderBackedTTSService


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


class _FakeAgentLoop:
    """Minimal AgentLoop stand-in — duck-typed for the bridge contract.

    ``process_message_stream`` is a sync generator (matching the real
    AgentLoop's contract) that yields whatever was passed at construction.
    """

    def __init__(self, events=None):
        self.events = events or []
        self.calls: list[tuple[str, str, dict]] = []

    def process_message_stream(self, session_id, user_message, **kwargs):
        self.calls.append((session_id, user_message, dict(kwargs)))
        for e in self.events:
            yield e


def _capture_push_frame(bridge: AgentLoopBridge):
    """Replace bridge.push_frame with a capture-list stub so we can assert on
    frame output without spinning up Pipecat's full TaskManager / setup
    machinery. Returns the capture list — populated as the bridge runs.
    """
    captured: list[tuple[Frame, FrameDirection]] = []

    async def _stub(frame, direction=FrameDirection.DOWNSTREAM):
        captured.append((frame, direction))

    bridge.push_frame = _stub  # type: ignore[method-assign]
    return captured


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline factory smoke
# ─────────────────────────────────────────────────────────────────────────────


def test_build_pipeline_constructs_all_processors():
    """Factory returns (Pipeline, PipelineWorker) with the expected processors
    wired in the documented order: input -> stt -> bridge -> tts -> output."""
    agent_loop = _FakeAgentLoop()

    async def _build():
        # aiohttp.ClientSession requires a running event loop at construction
        # (per aiohttp 3.x); the factory creates one internally if not passed.
        # Wrapping the build in asyncio.run() satisfies that requirement.
        connection = SmallWebRTCConnection()
        return build_aetheria_voice_pipeline(
            agent_loop=agent_loop,
            agent_name="aetheria",
            voice_id="voice-test-id",
            parakeet_url="http://127.0.0.1:8087",
            elevenlabs_api_key="test-key",
            session_id="session-1",
            webrtc_connection=connection,
        )

    pipeline, worker = asyncio.run(_build())
    assert isinstance(pipeline, Pipeline)
    assert isinstance(worker, PipelineWorker)

    # Walk the pipeline's processors. Pipeline composes a chain; the
    # constituent processors are stored on ``_processors``. We verify the
    # bridge + stt + tts are present in order (transport.input/output are
    # wrapper processors that sit at the ends).
    processors = list(pipeline._processors)
    type_names = [type(p).__name__ for p in processors]

    assert "VADProcessor" in type_names
    assert "TurnController" in type_names  # PR4a barge-in emitter
    assert "ParakeetSTTService" in type_names
    assert "AgentAdapterBridge" in type_names
    assert "ProviderBackedTTSService" in type_names
    assert "FirstAudioMetricsProbe" in type_names

    vad_idx = type_names.index("VADProcessor")
    tc_idx = type_names.index("TurnController")
    stt_idx = type_names.index("ParakeetSTTService")
    bridge_idx = type_names.index("AgentAdapterBridge")
    tts_idx = type_names.index("ProviderBackedTTSService")
    probe_idx = type_names.index("FirstAudioMetricsProbe")
    # Order: VAD → TurnController → STT → bridge → TTS → probe
    assert vad_idx < tc_idx < stt_idx < bridge_idx < tts_idx < probe_idx

    # Bridge holds the adapter wrapping agent_loop + session_id
    bridge = processors[bridge_idx]
    assert bridge._agent_loop is agent_loop
    assert bridge._session_id == "session-1"


def test_build_pipeline_passes_parakeet_url_through_to_stt_service():
    """Factory passes the parakeet_url straight through to ParakeetSTTService."""
    async def _build():
        connection = SmallWebRTCConnection()
        return build_aetheria_voice_pipeline(
            agent_loop=_FakeAgentLoop(),
            agent_name="aetheria",
            voice_id="v",
            parakeet_url="http://10.0.0.5:9999",
            elevenlabs_api_key="k",
            session_id="s",
            webrtc_connection=connection,
        )

    pipeline, _ = asyncio.run(_build())
    stt = next(p for p in pipeline._processors if isinstance(p, ParakeetSTTService))
    assert stt.transcribe_url == "http://10.0.0.5:9999/transcribe"


def test_pipeline_params_omit_allow_interruptions():
    """Pipecat 1.3.0 dropped allow_interruptions; must not pass the dead kwarg."""
    import inspect
    from pipecat.pipeline.worker import PipelineParams

    sig = inspect.signature(PipelineParams)
    # Field absent from constructor / model
    assert "allow_interruptions" not in sig.parameters
    # Building with only enable_metrics must succeed
    p = PipelineParams(enable_metrics=True)
    assert p is not None


def test_build_pipeline_uses_duplex_vad_and_first_audio_probe():
    """Factory applies DuplexConfig and inserts FirstAudioMetricsProbe."""
    from soveryn.platform.voice.duplex_config import DuplexConfig

    async def _build():
        connection = SmallWebRTCConnection()
        duplex = DuplexConfig(
            barge_in=False,
            confidence=0.3,
            start_secs=0.1,
            stop_secs=0.3,
            metrics_enabled=False,
        )
        return build_aetheria_voice_pipeline(
            agent_loop=_FakeAgentLoop(),
            agent_name="aetheria",
            voice_id="vid",
            parakeet_url="http://127.0.0.1:8087",
            elevenlabs_api_key="key",
            session_id="s1",
            webrtc_connection=connection,
            duplex=duplex,
        )

    pipeline, worker = asyncio.run(_build())
    assert isinstance(pipeline, Pipeline)
    assert isinstance(worker, PipelineWorker)
    names = [type(p).__name__ for p in pipeline._processors]
    assert "FirstAudioMetricsProbe" in names
    assert "AgentAdapterBridge" in names


def test_house_metrics_do_not_clobber_pipecat_frame_metrics():
    """PR1 regression: TurnMetricsTracker must not overwrite FrameProcessor._metrics.

    Pipecat setup() calls self._metrics.setup(task_manager). Storing our
    house tracker on that attribute kills the voice pipeline on start
    with AttributeError — Aetheria connects but never speaks.
    """
    from pipecat.processors.metrics.frame_processor_metrics import (
        FrameProcessorMetrics,
    )

    from soveryn.platform.voice.metrics import TurnMetricsTracker
    from soveryn.platform.voice.pipeline import (
        AgentAdapterBridge,
        FirstAudioMetricsProbe,
        ParakeetSTTService,
    )

    house = TurnMetricsTracker(agent="aetheria", session_id="s", enabled=False)

    probe = FirstAudioMetricsProbe(metrics=house)
    assert isinstance(probe._metrics, FrameProcessorMetrics)
    assert probe._turn_metrics is house

    stt = ParakeetSTTService(metrics=house)
    assert isinstance(stt._metrics, FrameProcessorMetrics)
    assert stt._turn_metrics is house

    class _Adapter:
        agent_id = "aetheria"
        voice_id = "aetheria"
        supports_streaming = True

        async def start_turn(self, **kwargs):
            if False:  # pragma: no cover
                yield None
            return

        async def on_cancelled(self, **kwargs):
            pass

        async def on_session_end(self, **kwargs):
            pass

    bridge = AgentAdapterBridge(adapter=_Adapter(), session_id="s", metrics=house)
    assert isinstance(bridge._metrics, FrameProcessorMetrics)
    assert bridge._turn_metrics is house


def test_build_pipeline_wires_voice_id_into_tts_service():
    """The configured voice_id reaches the provider-backed TTS service.

    The default provider is F5-TTS (SOVEREIGN_TTS_PRIMARY=f5tts); the
    voice_id selects the server-side voice (e.g. "aetheria").
    """
    import os
    # Force the local provider so the test doesn't depend on env state.
    prior = os.environ.pop("SOVEREIGN_TTS_PRIMARY", None)
    try:
        async def _build():
            connection = SmallWebRTCConnection()
            return build_aetheria_voice_pipeline(
                agent_loop=_FakeAgentLoop(),
                agent_name="aetheria",
                voice_id="aetheria",
                parakeet_url="http://127.0.0.1:8087",
                elevenlabs_api_key="k",
                session_id="s",
                webrtc_connection=connection,
            )

        pipeline, _ = asyncio.run(_build())
    finally:
        if prior is not None:
            os.environ["SOVEREIGN_TTS_PRIMARY"] = prior

    tts = next(p for p in pipeline._processors if isinstance(p, ProviderBackedTTSService))
    assert tts.voice_id == "aetheria"
    assert tts.provider_name == "f5tts"


# ─────────────────────────────────────────────────────────────────────────────
# ParakeetSTTService — URL construction + POST contract
# ─────────────────────────────────────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, status, payload):
        self.status = status
        self._payload = payload

    async def json(self):
        return self._payload

    async def text(self):
        return ""

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None


class _FakeAiohttpSession:
    def __init__(self, response):
        self.response = response
        self.calls: list[dict] = []

    def post(self, url, *, data, headers, timeout):
        self.calls.append({
            "url": url,
            "data": data,
            "headers": headers,
            "timeout": timeout,
        })
        return self.response


def test_parakeet_stt_service_strips_trailing_slash_on_url():
    stt = ParakeetSTTService(url="http://127.0.0.1:8087/", sample_rate=16000)
    assert stt.transcribe_url == "http://127.0.0.1:8087/transcribe"


def test_parakeet_stt_service_default_url_is_localhost_8087():
    stt = ParakeetSTTService(sample_rate=16000)
    assert stt.transcribe_url == DEFAULT_PARAKEET_URL + "/transcribe"


def test_parakeet_stt_service_posts_to_correct_url():
    async def _run():
        fake_resp = _FakeResponse(200, {"text": "hello world"})
        fake_session = _FakeAiohttpSession(fake_resp)
        stt = ParakeetSTTService(
            url="http://127.0.0.1:8087",
            sample_rate=16000,
            aiohttp_session=fake_session,
        )
        frames = []
        async for frame in stt.run_stt(b"WAV-BYTES"):
            if frame is not None:
                frames.append(frame)
        return frames, fake_session

    frames, fake_session = asyncio.run(_run())
    assert len(fake_session.calls) == 1
    assert fake_session.calls[0]["url"] == "http://127.0.0.1:8087/transcribe"
    assert fake_session.calls[0]["data"] == b"WAV-BYTES"
    assert fake_session.calls[0]["headers"] == {"Content-Type": "audio/wav"}
    # One TranscriptionFrame surfaced
    assert len(frames) == 1
    assert isinstance(frames[0], TranscriptionFrame)
    assert frames[0].text == "hello world"


def test_parakeet_stt_service_returns_silently_on_empty_audio():
    async def _run():
        fake_session = _FakeAiohttpSession(_FakeResponse(200, {"text": "x"}))
        stt = ParakeetSTTService(aiohttp_session=fake_session)
        frames = []
        async for frame in stt.run_stt(b""):
            frames.append(frame)
        return frames, fake_session

    frames, fake_session = asyncio.run(_run())
    assert frames == []
    assert fake_session.calls == []  # never called the API


def test_parakeet_stt_service_drops_non200_responses_silently():
    async def _run():
        fake_session = _FakeAiohttpSession(_FakeResponse(500, {}))
        stt = ParakeetSTTService(aiohttp_session=fake_session)
        frames = []
        async for frame in stt.run_stt(b"audio"):
            frames.append(frame)
        return frames

    assert asyncio.run(_run()) == []


def test_parakeet_stt_service_is_segmented_stt_subclass():
    """SegmentedSTTService is the base contract — confirms we picked the
    right base class so VAD-bounded buffering + WAV encoding works."""
    assert issubclass(ParakeetSTTService, SegmentedSTTService)


# ─────────────────────────────────────────────────────────────────────────────
# AgentLoopBridge — frame contract via push_frame stub
# ─────────────────────────────────────────────────────────────────────────────


def test_agent_loop_bridge_emits_llm_text_frames_for_each_tts_token_event():
    """Bridge consumes a TranscriptionFrame, runs the AgentLoop generator,
    and emits aggregated LLMTextFrame(s) via sentence-level aggregation —
    bracketed by LLMFullResponseStartFrame and LLMFullResponseEndFrame.

    Commit fa68d05 (2026-06-15): TTS uses SENTENCE aggregation, so tokens
    are buffered until a sentence terminator is seen.  The three tokens
    "hello", " world", "." flush together as one frame "hello world."."""

    async def _run():
        agent_loop = _FakeAgentLoop(events=[
            TTSTokenEvent(text="hello"),
            TTSTokenEvent(text=" world"),
            TTSTokenEvent(text="."),
        ])
        bridge = AgentLoopBridge(agent_loop=agent_loop, session_id="sid-1")
        captured = _capture_push_frame(bridge)

        # Drive the bridge's turn directly (skipping process_frame's
        # super().process_frame() chain that requires full Pipecat setup).
        await bridge._run_turn("user utterance")
        return captured, agent_loop

    captured, agent_loop = asyncio.run(_run())

    # AgentLoop was called with the transcribed user utterance + source=voice
    assert len(agent_loop.calls) == 1
    assert agent_loop.calls[0][0] == "sid-1"
    assert agent_loop.calls[0][1] == "user utterance"
    assert agent_loop.calls[0][2].get("source") == "voice"

    # Captured: response wrapper Start, one aggregated LLMTextFrame, response End.
    # Sentence aggregation flushes "hello" + " world" + "." as one frame.
    frame_types = [type(f).__name__ for f, _ in captured]
    text_frames = [f for f, _ in captured if isinstance(f, LLMTextFrame)]
    starts = [f for f, _ in captured if isinstance(f, LLMFullResponseStartFrame)]
    ends = [f for f, _ in captured if isinstance(f, LLMFullResponseEndFrame)]

    assert [f.text for f in text_frames] == ["hello world."]
    assert len(starts) == 1
    assert len(ends) == 1
    # Order: Start ... End
    assert frame_types[0] == "LLMFullResponseStartFrame"
    assert frame_types[-1] == "LLMFullResponseEndFrame"


def test_agent_loop_bridge_skips_non_tts_token_events():
    """Bridge ignores TokenEvent / DoneEvent / etc — only TTSTokenEvent flows."""

    async def _run():
        @dataclass(frozen=True)
        class _IgnoredEvent:
            payload: str

        agent_loop = _FakeAgentLoop(events=[
            _IgnoredEvent(payload="should-not-appear"),
            TTSTokenEvent(text="spoken"),
            _IgnoredEvent(payload="also-skipped"),
        ])
        bridge = AgentLoopBridge(agent_loop=agent_loop, session_id="sid-2")
        captured = _capture_push_frame(bridge)
        await bridge._run_turn("hi")
        return captured

    captured = asyncio.run(_run())
    text_frames = [f for f, _ in captured if isinstance(f, LLMTextFrame)]
    assert [f.text for f in text_frames] == ["spoken"]


def test_agent_loop_bridge_sanitizes_tts_text_as_safety_net():
    """Even if a stray TTSTokenEvent slips through with markup, the bridge's
    sanitize_for_tts safety net keeps the wire output clean."""
    async def _run():
        agent_loop = _FakeAgentLoop(events=[
            TTSTokenEvent(text="<think>hidden</think>visible part"),
        ])
        bridge = AgentLoopBridge(agent_loop=agent_loop, session_id="sid-3")
        captured = _capture_push_frame(bridge)
        await bridge._run_turn("hi")
        return captured

    captured = asyncio.run(_run())
    text_frames = [f for f, _ in captured if isinstance(f, LLMTextFrame)]
    assert len(text_frames) == 1
    assert "<think>" not in text_frames[0].text
    assert "hidden" not in text_frames[0].text
    assert "visible part" in text_frames[0].text


def test_agent_loop_bridge_skips_empty_sanitized_chunks():
    """If a TTSTokenEvent has text that sanitizes to nothing (pure markup),
    no LLMTextFrame is emitted for it — but the wrapper Start/End still
    flush so TTS sees a coherent turn."""
    async def _run():
        agent_loop = _FakeAgentLoop(events=[
            TTSTokenEvent(text="<think>pure</think>"),  # sanitizes to ""
        ])
        bridge = AgentLoopBridge(agent_loop=agent_loop, session_id="sid-4")
        captured = _capture_push_frame(bridge)
        await bridge._run_turn("hi")
        return captured

    captured = asyncio.run(_run())
    text_frames = [f for f, _ in captured if isinstance(f, LLMTextFrame)]
    starts = [f for f, _ in captured if isinstance(f, LLMFullResponseStartFrame)]
    ends = [f for f, _ in captured if isinstance(f, LLMFullResponseEndFrame)]
    assert text_frames == []
    assert len(starts) == 1
    assert len(ends) == 1


def test_agent_loop_bridge_cancels_on_interruption_frame():
    """When _run_turn's asyncio.Task is cancelled mid-turn, an
    LLMFullResponseEndFrame is still emitted so the downstream TTS service
    can drop pending audio cleanly. Mimics the real interruption path where
    process_frame -> _cancel_inflight cancels the task.

    Sentence aggregation note (fa68d05): the bridge only flushes a frame at
    sentence boundaries (or when the buffer hits 40 chars).  The pre-cancel
    chunk must end with a sentence terminator so it flushes BEFORE cancellation;
    otherwise it stays buffered and the wait loop never fires."""

    async def _run():
        # Slow generator: emits one complete sentence, then blocks until
        # externally signalled cancelled. We cancel the task partway through
        # and assert the End frame still fires from the finally block.
        cancel_signal = {"cancel": False}

        class _SlowAgentLoop:
            def process_message_stream(self, session_id, user_message, **kwargs):
                # "first." ends with "." → flushes immediately under sentence aggregation
                yield TTSTokenEvent(text="first.")
                # Spin until the test signals cancel
                deadline = time.monotonic() + 5.0
                while time.monotonic() < deadline:
                    time.sleep(0.005)
                    if cancel_signal["cancel"]:
                        return
                yield TTSTokenEvent(text="never")

        agent_loop = _SlowAgentLoop()
        bridge = AgentLoopBridge(agent_loop=agent_loop, session_id="sid-x")
        captured = _capture_push_frame(bridge)

        # Spawn the turn as a task so we can cancel it externally.
        turn_task = asyncio.create_task(bridge._run_turn("hi"))

        # Wait for the first chunk to land.
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            await asyncio.sleep(0.005)
            if any(isinstance(f, LLMTextFrame) for f, _ in captured):
                break

        # Cancel the task (mimics what _cancel_inflight does)
        turn_task.cancel()
        cancel_signal["cancel"] = True  # let the producer thread exit
        try:
            await turn_task
        except asyncio.CancelledError:
            pass

        return captured

    captured = asyncio.run(_run())

    text_frames = [f for f, _ in captured if isinstance(f, LLMTextFrame)]
    starts = [f for f, _ in captured if isinstance(f, LLMFullResponseStartFrame)]
    ends = [f for f, _ in captured if isinstance(f, LLMFullResponseEndFrame)]

    # Got the first sentence before cancellation (flushed at "." boundary)
    assert any(f.text == "first." for f in text_frames)
    # Never got the second chunk (the cancellation interrupted the wait)
    assert not any(f.text == "never" for f in text_frames)
    # Start + End wrappers both fired (End emitted in the finally block)
    assert len(starts) == 1
    assert len(ends) == 1
