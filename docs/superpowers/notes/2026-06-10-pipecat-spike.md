# Pipecat investigation spike — Sovereign Voice Phase 1

**Date:** 2026-06-10
**Author:** spike subagent (research-only, no SOVERYN code written)
**Scope:** Validate Pipecat as the foundation for Aetheria's sovereign voice pipeline
**Related:** `docs/superpowers/specs/2026-06-10-sovereign-voice-design.md`, `docs/superpowers/plans/2026-06-10-sovereign-voice-phase1.md`

---

## 1. TL;DR

**Pipecat fits. Build Phase 1 on it.** The make-or-break question (Q4: browser WebRTC without Daily.co cloud) resolves cleanly: `SmallWebRTCTransport` is a first-class peer-to-peer transport, no API keys, no Daily.co dependency, and is what every getting-started example in the official Pipecat-examples repo uses. The current release (1.3.0, 2026-05-28) is multi-agent-aware, has built-in `SileroVADAnalyzer`, ships `ElevenLabsHttpTTSService` (and a streaming WebSocket variant), provides `SegmentedSTTService` as a near-perfect base class for our Parakeet HTTP wrapper, and bakes interruption / barge-in into the pipeline via `InterruptionFrame` + `UserStartedSpeakingFrame` semantics. One non-blocking note: in 1.3.0, `PipelineTask` → `PipelineWorker` and `PipelineRunner` → `WorkerRunner` (the old names still resolve with `DeprecationWarning`). Use the new names. No reason to escalate to LiveKit.

---

## 2. Q1 — API shape

**Pipeline construction (Pipecat 1.3.0):**

```python
# Imports (verified against pipecat-examples voice-agent bot.py @ main)
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.workers.runner import WorkerRunner
```

**Architectural shape** (taken from the official `p2p-webrtc/voice-agent/bot.py` example, adapted for SOVERYN — Parakeet STT, AgentLoop bridge, ElevenLabs TTS):

```python
async def run_aetheria_voice_session(webrtc_connection):
    # 1. Transport: SmallWebRTCTransport handles browser <-> server WebRTC
    transport = SmallWebRTCTransport(
        webrtc_connection=webrtc_connection,
        params=TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_out_10ms_chunks=2,    # tunable: 20ms output frames
        ),
    )

    # 2. VAD — explicit processor in the graph, not just a transport param.
    #    This is the missing stage that turns audio frames into
    #    VADUserStartedSpeakingFrame / VADUserStoppedSpeakingFrame for STT.
    vad = SileroVADAnalyzer(
        sample_rate=16000,
        params=VADParams(
            confidence=0.7,         # default 0.7 — speech probability threshold (0..1)
            start_secs=0.2,         # default 0.2 — seconds of speech before SPEAKING state
            stop_secs=0.2,          # default 0.2 — seconds of silence before QUIET state
            min_volume=0.6,         # default 0.6 — minimum audio volume (0..1)
        ),
    )

    # 3. STT — our custom Parakeet HTTP wrapper (see Q6)
    stt = ParakeetSegmentedSTTService(
        url="http://127.0.0.1:8087",
        sample_rate=16000,
    )

    # 4. LLM bridge — our custom FrameProcessor wrapping AgentLoop (see Q5)
    llm_bridge = AgentLoopBridge(agent_loop=aetheria_agent_loop)

    # 5. TTS — Pipecat's built-in ElevenLabs service
    from pipecat.services.elevenlabs.tts import ElevenLabsHttpTTSService
    import aiohttp
    aiohttp_session = aiohttp.ClientSession()
    tts = ElevenLabsHttpTTSService(
        api_key=os.environ["ELEVENLABS_API_KEY"],
        voice_id=os.environ["ELEVENLABS_VOICE_ID_AETHERIA"],
        aiohttp_session=aiohttp_session,
    )

    # 5. Pipeline — frames flow left-to-right downstream, upstream signals (interrupt) flow right-to-left
    pipeline = Pipeline([
        transport.input(),     # audio in from browser mic
        VADProcessor(vad_analyzer=vad),  # AudioRawFrame -> VADUserStartedSpeakingFrame / VADUserStoppedSpeakingFrame
        stt,                   # VAD-bounded AudioRawFrame -> TranscriptionFrame
        llm_bridge,            # TranscriptionFrame -> LLMTextFrame (sanitized) stream
        tts,                   # LLMTextFrame -> TTSAudioRawFrame
        transport.output(),    # audio out to browser speakers
    ])

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,    # see Q3 — default True in 1.3.0
            enable_metrics=True,
        ),
    )

    @transport.event_handler("on_client_connected")
    async def on_connected(t, client):
        # Optional greeting; not required for Phase 1
        pass

    @transport.event_handler("on_client_disconnected")
    async def on_disconnected(t, client):
        await worker.cancel()

    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    await runner.run()
```

**Notes:**
- `PipelineWorker` is the new name for `PipelineTask` (renamed in 1.3.0 per the multi-agent refactor in [PR #4493](https://github.com/pipecat-ai/pipecat/pull/4493) — old name still resolves with a `DeprecationWarning`).
- `WorkerRunner` is the new name for `PipelineRunner` (also 1.3.0 rename).
- The reference example uses `GeminiLiveLLMService` (a speech-to-speech model) that bypasses STT/TTS — we're not doing that; we have a discrete STT/LLM/TTS pipeline because our LLM (AgentLoop fronting llama.cpp Qwen3.6) is text-only.

**Citations:**
- [pipecat-examples / p2p-webrtc / voice-agent / bot.py](https://github.com/pipecat-ai/pipecat-examples/blob/main/p2p-webrtc/voice-agent/bot.py)
- [Pipecat CHANGELOG 1.3.0](https://github.com/pipecat-ai/pipecat/blob/main/CHANGELOG.md)
- [Pipeline & Frame Processing guide](https://docs.pipecat.ai/guides/learn/pipeline)

---

## 3. Q2 — VAD

**Yes, Pipecat ships `SileroVADAnalyzer` out of the box.**

```python
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams

vad = SileroVADAnalyzer(
    sample_rate=16000,          # required: 8000 or 16000 Hz
    params=VADParams(
        confidence=0.7,         # default 0.7 — speech probability threshold (0..1)
        start_secs=0.2,         # default 0.2 — seconds of speech before SPEAKING state
        stop_secs=0.2,          # default 0.2 — seconds of silence before QUIET state
        min_volume=0.6,         # default 0.6 — minimum audio volume (0..1)
    ),
)
```

It uses the Silero VAD ONNX model under the hood (so it pulls `onnxruntime` via the `[silero]` extra). Frame size is fixed by Silero: 512 samples at 16 kHz, 256 at 8 kHz.

**Wire it via `VADProcessor(vad_analyzer=SileroVADAnalyzer(...))` in the pipeline graph** — that processor emits `VADUserStartedSpeakingFrame` / `VADUserStoppedSpeakingFrame`, which `SegmentedSTTService` consumes to define utterance boundaries (see Q6). `TransportParams.audio_in_sample_rate` still matters for resampling, but it does not itself create the VAD event stream.

**Tunable knobs for SOVERYN:**
- Bump `confidence` up to ~0.8 if Jon's desk has typing/fan noise → fewer false starts.
- Bump `stop_secs` up to ~0.4 if Aetheria gets cut off mid-thinking-pause when she's still gathering response — too low = chops off her trailing-off speech; too high = laggy turn-taking.
- The DEV-community piece below shows a "sensitive vs conservative" preset pattern that's worth borrowing.

**Citations:**
- [SileroVADAnalyzer API reference](https://reference-server.pipecat.ai/en/stable/api/pipecat.audio.vad.silero.html)
- [SileroVADAnalyzer docs](https://docs.pipecat.ai/server/utilities/audio/silero-vad-analyzer)
- [VAD module reference](https://reference-server.pipecat.ai/en/latest/api/pipecat.audio.vad.html)

---

## 4. Q3 — Interruption / barge-in

**Built-in. Pipecat handles it as a first-class frame-routing concept; we don't implement it.**

The mechanics, per Pipecat 1.3.0:

1. The transport (driven by `vad_analyzer`) detects user speech mid-bot-talk and emits a `StartInterruptionFrame` (a `SystemFrame`, bypasses the normal queue and is dispatched directly downstream).
2. `StartInterruptionFrame` is immediately followed by `UserStartedSpeakingFrame`.
3. Every `FrameProcessor` downstream that holds in-flight work (LLM streaming, TTS audio rendering) sees `InterruptionFrame` in `process_frame()` and cancels:
   - `LLMService.process_frame` → `_handle_interruptions(frame)` → cancels in-flight function calls registered with `cancel_on_interruption=True`.
   - `TTSService.process_frame` → `_handle_interruption(frame, direction)` → drops pending audio in the serialization queue.
   - `STTService.process_frame` → `_reset_stt_ttfb_state()` (resets timing, doesn't kill audio).
4. The pipeline becomes responsive to the new user audio immediately.

**Configuration:**

```python
from pipecat.pipeline.worker import PipelineParams, PipelineWorker

worker = PipelineWorker(
    pipeline,
    params=PipelineParams(
        allow_interruptions=True,    # default True in 1.3.0
        # Note: docs say allow_interruptions is in the process of being deprecated
        # in favor of User Turn Strategies; True is still the right call for Phase 1.
    ),
)
```

**For SOVERYN: AgentLoop bridge must cooperate.** Our `AgentLoopBridge` (Q5) needs to:
- Hold a reference to the in-flight `process_message_stream` generator (or its task).
- On `InterruptionFrame` in `process_frame()`, cancel that task so AgentLoop stops emitting `TTSTokenEvent`s, then call `super().process_frame()` to let the frame propagate.

```python
# Sketch — in our AgentLoopBridge FrameProcessor
class AgentLoopBridge(FrameProcessor):
    def __init__(self, agent_loop: AgentLoop):
        super().__init__()
        self._agent_loop = agent_loop
        self._inflight_task: asyncio.Task | None = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, InterruptionFrame):
            # Cancel our in-flight AgentLoop generator
            if self._inflight_task is not None and not self._inflight_task.done():
                self._inflight_task.cancel()
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, TranscriptionFrame):
            # New user utterance — kick off AgentLoop streaming
            await self._start_inflight(frame.text)
            return

        await self.push_frame(frame, direction)
```

**The PipelineWorker also exposes `worker.cancel()`** for the on-client-disconnected path; that's the harder shutdown.

**Citations:**
- [Pipecat src/services/llm_service.py — `_handle_interruptions`](https://raw.githubusercontent.com/pipecat-ai/pipecat/main/src/pipecat/services/llm_service.py) (lines around `_handle_interruptions`)
- [Pipecat src/services/tts_service.py — `_handle_interruption`](https://raw.githubusercontent.com/pipecat-ai/pipecat/main/src/pipecat/services/tts_service.py) (line ~914)
- [Frames API reference (InterruptionFrame, UserStartedSpeakingFrame)](https://reference-server.pipecat.ai/en/stable/api/pipecat.frames.frames.html)

---

## 5. Q4 — WebRTC for browser (CRITICAL)

**RESOLVED: Pipecat supports browser-only WebRTC without Daily.co. Build proceeds on Pipecat.**

The transport is `SmallWebRTCTransport`, lives in `pipecat.transports.smallwebrtc.transport`, and is explicitly the peer-to-peer / serverless path. From the official docs:

> "SmallWebRTCTransport enables peer-to-peer ('serverless') WebRTC connections between clients and your Pipecat application. This transport is open source and self-contained, with no dependencies on any other infrastructure."

> "No API keys are required since this is a peer-to-peer transport implementation. … All of the Pipecat examples and getting started repos use SmallWebRTCTransport."

**This is exactly what SOVERYN needs.** All bytes stay on `127.0.0.1`. No cloud dependency. The official `p2p-webrtc/voice-agent` example in the pipecat-examples repo is the canonical pattern, and we read its actual source.

**The server-side signaling pattern (verified from `p2p-webrtc/voice-agent/server.py`):**

```python
from pipecat.transports.smallwebrtc.request_handler import (
    SmallWebRTCPatchRequest,
    SmallWebRTCRequest,
    SmallWebRTCRequestHandler,
)

# Single handler instance, reused per offer
small_webrtc_handler = SmallWebRTCRequestHandler()

# POST /api/offer — initial SDP offer from browser, returns SDP answer
async def offer(request: SmallWebRTCRequest, background_tasks):
    async def webrtc_connection_callback(connection):
        # `connection` is a SmallWebRTCConnection; pass it to your bot runner
        background_tasks.add_task(run_aetheria_voice_session, connection)

    answer = await small_webrtc_handler.handle_web_request(
        request=request,
        webrtc_connection_callback=webrtc_connection_callback,
    )
    return answer

# PATCH /api/offer — trickle ICE candidates
async def ice_candidate(request: SmallWebRTCPatchRequest):
    await small_webrtc_handler.handle_patch_request(request)
    return {"status": "success"}
```

The reference server.py uses FastAPI, but the pattern is framework-agnostic — `SmallWebRTCRequestHandler.handle_web_request()` takes a typed request and returns the answer. For SOVERYN's Flask blueprint we can either:
- (a) **Mount a small FastAPI sub-app inside Flask for `/voice/<agent>/offer`** — cleanest because `SmallWebRTCRequest` is a Pydantic model in the request handler signature.
- (b) **Use `SmallWebRTCConnection` directly without `SmallWebRTCRequestHandler`** and do our own offer/answer JSON dispatch in a vanilla Flask view — viable but takes more lines.

**Recommendation for Task 5 (`/voice` blueprint):** use option (a). Mount a FastAPI app at `/api/voice/...` for SDP signaling and keep Flask for the user-facing `/voice/<agent>` HTML serving. The two coexist behind a WSGI/ASGI middleware (Flask handles the synchronous HTML+static, FastAPI handles the async WebRTC handshake). Or — simpler — port the whole voice blueprint to FastAPI if Aetheria's other surfaces are pure Flask and isolation is fine.

**Browser-side client (verified from `p2p-webrtc/voice-agent/index.html`):** plain `RTCPeerConnection` — no special SDK required for a minimal client.

```javascript
const pc = new RTCPeerConnection({
    iceServers: [{ urls: "stun:stun.l.google.com:19302" }]
});

// IMPORTANT: SmallWebRTCTransport expects BOTH audio and video transceivers,
// even for voice-only (just don't attach a video track):
pc.addTransceiver(audioTrack, { direction: 'sendrecv' });
pc.addTransceiver('video', { direction: 'sendrecv' });

await pc.setLocalDescription(await pc.createOffer());
const response = await fetch('/api/voice/aetheria/offer', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sdp: pc.localDescription.sdp, type: 'offer' }),
});
const answer = await response.json();
pc.pc_id = answer.pc_id;
await pc.setRemoteDescription(answer);

// Trickle ICE — PATCH each candidate as it arrives
pc.onicecandidate = (event) => {
    if (event.candidate) {
        fetch('/api/voice/aetheria/offer', {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                pc_id: pc.pc_id,
                candidates: [{
                    candidate: event.candidate.candidate,
                    sdp_mid: event.candidate.sdpMid,
                    sdp_mline_index: event.candidate.sdpMLineIndex,
                }],
            }),
        });
    }
};

pc.ontrack = (e) => { audioEl.srcObject = e.streams[0]; };
```

**Or use the official `@pipecat-ai/small-webrtc-transport` npm package** if we want richer client lifecycle (event handlers for connection state, etc.). For Phase 1 the vanilla `RTCPeerConnection` is enough — the orb already has its own JS, no need for a heavy SDK.

**Bottom line on Q4: Pipecat WINS this one decisively. No need to consider LiveKit.**

**Citations:**
- [SmallWebRTCTransport docs](https://docs.pipecat.ai/server/services/transport/small-webrtc)
- [pipecat-examples / p2p-webrtc / voice-agent / server.py](https://github.com/pipecat-ai/pipecat-examples/blob/main/p2p-webrtc/voice-agent/server.py)
- [pipecat-examples / p2p-webrtc / voice-agent / index.html](https://github.com/pipecat-ai/pipecat-examples/blob/main/p2p-webrtc/voice-agent/index.html)
- [Daily blog: You don't need a WebRTC server for your voice agents](https://www.daily.co/blog/you-dont-need-a-webrtc-server-for-your-voice-agents/)
- [pipecat-ai-small-webrtc-prebuilt on PyPI](https://pypi.org/project/pipecat-ai-small-webrtc-prebuilt/)
- [@pipecat-ai/small-webrtc-transport on npm](https://www.npmjs.com/package/@pipecat-ai/small-webrtc-transport)

---

## 6. Q5 — Streaming AgentLoop bridge

**Pattern: custom `FrameProcessor` that consumes `TranscriptionFrame` (from STT) and emits `LLMFullResponseStartFrame` → `LLMTextFrame`(s) → `LLMFullResponseEndFrame` (consumed by TTS).** We do NOT subclass `LLMService`; we sit between STT and TTS as a plain processor.

**Why not subclass `LLMService`:**
- `LLMService` has heavy machinery for function-call registration, OpenAI-shaped context handling, `LLMContext` aggregators, `run_inference()` for out-of-band summarization, realtime-service metadata, and assumes you're calling a chat-completions-style API. Adopting all that to wrap our local `AgentLoop` is fighting the abstraction.
- Pipecat's frame contract for "LLM produced text → feed to TTS" is just:
  - Emit `LLMFullResponseStartFrame()` to open the assistant turn.
  - Stream one or more `LLMTextFrame(text=...)` with the streaming text chunks.
  - Emit `LLMFullResponseEndFrame()` to close the turn (`TTSService` flushes its audio context).

The `TTSService` base class watches for these frames (look at the import list near the top of `tts_service.py` — both frames are imported as first-class signals).

**Recommended bridge shape:**

```python
import asyncio
from pipecat.frames.frames import (
    Frame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    StartFrame,
    TranscriptionFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from soveryn.agents.loop import AgentLoop, TTSTokenEvent
from soveryn.platform.voice.sanitize import sanitize_for_tts


class AgentLoopBridge(FrameProcessor):
    """Bridges Pipecat <-> AgentLoop.process_message_stream.

    Inputs: TranscriptionFrame from STT.
    Outputs: LLMFullResponseStartFrame -> LLMTextFrame(s) -> LLMFullResponseEndFrame.
    Sanitization-at-source: AgentLoop emits TTSTokenEvent (pre-sanitized);
    if a chunk slips through with markup, sanitize_for_tts is a final safety net.
    """

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
            # finalized=True invariant from SegmentedSTTService (Q6) — we only
            # ever see complete utterances here
            text = frame.text.strip()
            if text:
                await self._cancel_inflight()
                self._inflight_task = asyncio.create_task(self._run_turn(text))
            return

        # pass everything else through
        await self.push_frame(frame, direction)

    async def _cancel_inflight(self):
        if self._inflight_task and not self._inflight_task.done():
            self._inflight_task.cancel()
            try:
                await self._inflight_task
            except (asyncio.CancelledError, Exception):
                pass
        self._inflight_task = None

    async def _run_turn(self, user_text: str):
        """Drive one AgentLoop turn, streaming TTSTokenEvents into LLMTextFrames."""
        await self.push_frame(LLMFullResponseStartFrame())
        try:
            # AgentLoop.process_message_stream is the existing async generator.
            # We subscribe to TTSTokenEvent only — the full content stream goes to
            # conv_store separately (existing behavior; not the voice channel's job).
            async for event in self._agent_loop.process_message_stream(
                session_id=self._session_id,
                message=user_text,
            ):
                if isinstance(event, TTSTokenEvent):
                    # Already sanitized at source (Task 2 + AgentLoop change in Task 4).
                    # sanitize_for_tts is idempotent — cheap final safety net.
                    chunk = sanitize_for_tts(event.text)
                    if chunk:
                        await self.push_frame(LLMTextFrame(text=chunk))
                # Other event types (TokenEvent, ToolCallEvent, DoneEvent) are ignored
                # by the bridge — they're for the UI/persistence path, not voice.
        except asyncio.CancelledError:
            # Interruption — let it propagate after emitting end frame
            raise
        finally:
            await self.push_frame(LLMFullResponseEndFrame())
```

**Key contract notes:**
- The bridge expects `AgentLoop.process_message_stream` to be an `async` generator (one of the assumptions in `loop.py`'s current shape). If it's currently a sync generator, wrap it once at the boundary with `asyncio.to_thread()` or `aiostream`.
- The `TTSTokenEvent` class is what Task 4 step 2 adds to `loop.py` — the bridge depends on that one-line change landing.
- This bridge sits BETWEEN STT and TTS in the pipeline; we do NOT include `LLMContextAggregatorPair` or the OpenAI-shaped context machinery because `AgentLoop` owns all conversation state already (lattice, conv_store, persona).
- **Important:** because we skip Pipecat's `LLMContextAggregatorPair`, we also skip its assistant aggregator which is what normally captures assistant text into the LLM's context. That's correct for us — AgentLoop persists turns itself into conv_store. The voice pipeline is "output-only" w.r.t. context; the source of truth is AgentLoop.

**Citations:**
- [LLMService source — `LLMFullResponseStartFrame`, `LLMFullResponseEndFrame`, `LLMTextFrame` imports and contract](https://raw.githubusercontent.com/pipecat-ai/pipecat/main/src/pipecat/services/llm_service.py)
- [FrameProcessor source — `process_frame`, `push_frame` contract](https://raw.githubusercontent.com/pipecat-ai/pipecat/main/src/pipecat/processors/frame_processor.py)
- [Pipeline & Frame Processing guide](https://docs.pipecat.ai/guides/learn/pipeline)
- [Anam: Frame processing in Pipecat](https://anam.ai/blog/pipecat-frame-processing-guide)

---

## 7. Q6 — Custom STT processor (Parakeet)

**Use `SegmentedSTTService`. It's a near-perfect fit for our existing Parakeet HTTP endpoint.**

`SegmentedSTTService` (in `pipecat.services.stt_service`) is the base class for STT services that operate on complete utterances (VAD-bounded segments), not continuous streaming. That matches Parakeet's interface: POST a WAV blob, get back a transcript.

The base class handles the heavy lifting for us:
- Subscribes to `VADUserStartedSpeakingFrame` / `VADUserStoppedSpeakingFrame` (emitted by `VADProcessor` wrapping `SileroVADAnalyzer`).
- Buffers `AudioRawFrame.audio` bytes from speech-start to speech-end.
- On speech-end, wraps the buffer as a WAV (16-bit mono PCM at the configured sample rate).
- Calls our `run_stt(audio: bytes)` with the WAV bytes.
- Marks the resulting `TranscriptionFrame` as `finalized=True` automatically.

We only override `run_stt`:

```python
from collections.abc import AsyncGenerator
from typing import Any
import aiohttp

from pipecat.frames.frames import Frame, TranscriptionFrame
from pipecat.services.stt_service import SegmentedSTTService
from pipecat.utils.time import time_now_iso8601


class ParakeetSTTService(SegmentedSTTService):
    """SOVERYN Parakeet HTTP wrapper.

    Parakeet is the locally-hosted STT model on http://127.0.0.1:8087.
    Endpoint: POST /transcribe with audio/wav body, returns {"text": "..."}.
    """

    def __init__(
        self,
        *,
        url: str = "http://127.0.0.1:8087",
        sample_rate: int = 16000,
        aiohttp_session: aiohttp.ClientSession | None = None,
        **kwargs: Any,
    ):
        super().__init__(sample_rate=sample_rate, **kwargs)
        self._url = url.rstrip("/") + "/transcribe"
        self._aiohttp_session = aiohttp_session  # may be None; lazily created

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame | None, None]:
        """audio is a WAV blob (16-bit mono PCM, sample_rate Hz).
        Yields a single TranscriptionFrame on success, or nothing on empty input.
        """
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
                    body = await response.text()
                    # Pipecat convention: log + return; upstream sees no frame
                    return
                payload = await response.json()
                text = (payload.get("text") or "").strip()
                if text:
                    yield TranscriptionFrame(
                        text=text,
                        user_id=self._user_id,
                        timestamp=time_now_iso8601(),
                    )
        except Exception as e:
            # Surface to Pipecat's ErrorFrame path if the spike-author confirms
            # the existing telemetry expectation; minimal version just swallows
            return
```

**The verified critical detail**: from reading `SegmentedSTTService._handle_user_stopped_speaking()` source — it constructs a WAV header (16-bit, mono, sample_rate) inside an `io.BytesIO` and passes the resulting bytes to `run_stt`. So Parakeet receives a properly-framed WAV, not raw PCM. The existing Parakeet endpoint already accepts WAV uploads (per `project_soveryn_voice_pipeline.md`), so this just works.

**`TranscriptionFrame` constructor signature** (from pipecat.frames.frames):
```python
TranscriptionFrame(text=str, user_id=str, timestamp=str, language=Language | None=None)
```

The base class sets `finalized=True` on the frame before push_frame (we verified this in source — see the SegmentedSTTService.push_frame override). So downstream (`AgentLoopBridge`) can rely on every `TranscriptionFrame` it sees being a complete utterance.

**Citations:**
- [Pipecat src/services/stt_service.py — `SegmentedSTTService`](https://raw.githubusercontent.com/pipecat-ai/pipecat/main/src/pipecat/services/stt_service.py)
- [STTService API reference](https://reference-server.pipecat.ai/en/stable/api/pipecat.services.stt_service.html)
- [Frames API reference (TranscriptionFrame)](https://reference-server.pipecat.ai/en/stable/api/pipecat.frames.frames.html)

---

## 8. Q7 — Custom TTS processor (ElevenLabs)

**Don't write one. Pipecat ships `ElevenLabsHttpTTSService` and `ElevenLabsTTSService` (WebSocket).**

```python
from pipecat.services.elevenlabs.tts import ElevenLabsHttpTTSService  # HTTP, simpler
# or:
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService      # WebSocket, lower latency
```

**Recommended for Phase 1: `ElevenLabsHttpTTSService`.** Simpler dependency surface, no WebSocket connection lifecycle to manage, latency is fine for first ship. Phase 3 can swap to the WebSocket variant if first-audio-out latency telemetry shows the HTTP round-trip is the bottleneck.

```python
import aiohttp
from pipecat.services.elevenlabs.tts import ElevenLabsHttpTTSService

aiohttp_session = aiohttp.ClientSession()
tts = ElevenLabsHttpTTSService(
    api_key=os.environ["ELEVENLABS_API_KEY"],
    voice_id=os.environ["ELEVENLABS_VOICE_ID_AETHERIA"],
    aiohttp_session=aiohttp_session,
    # Optional: model_id, output_format, sample_rate, voice_settings
)
```

The base `TTSService.run_tts(text, context_id) -> AsyncGenerator[Frame | None]` contract is implemented by the ElevenLabs services already — they yield `TTSAudioRawFrame` chunks as audio arrives, plus `TTSStartedFrame`/`TTSStoppedFrame` envelopes.

**Phase 2 implications (out of scope for this spike but worth flagging):** when we add local TTS via the `TTSProvider` interface in `soveryn/platform/voice/providers/`, the Task 3 / Task 4 implementer can either:
- (a) Build `LocalTTSProvider` against our own `TTSProvider` ABC and bridge it to Pipecat via a custom `TTSService` subclass that delegates `run_tts` to the provider. This keeps Phase 2's local-TTS evaluation portable across orchestrators.
- (b) Subclass `pipecat.services.tts_service.TTSService` directly for local TTS and skip our own ABC.

Option (a) preserves the "the orchestrator doesn't care which provider it calls" architecture in the spec. The Phase 1 `TTSProvider` ABC and `ElevenLabsTTSProvider` (Task 3) build are still worth doing — they're the Phase 2 boundary. For Phase 1, **the actual pipeline wiring uses Pipecat's built-in `ElevenLabsHttpTTSService` directly**, and our `ElevenLabsTTSProvider` (Task 3) sits ready as the integration point for Phase 2's local TTS swap.

This means: Task 3 is somewhat speculative for Phase 1 — but it's still worth shipping as the abstract base + ElevenLabs reference impl because Phase 2 needs the contract documented. Just don't wire it into the Phase 1 pipeline; Phase 1's pipeline calls `ElevenLabsHttpTTSService` directly.

**Citations:**
- [ElevenLabs service docs](https://docs.pipecat.ai/api-reference/server/services/tts/elevenlabs)
- [ElevenLabs TTS API reference](https://reference-server.pipecat.ai/en/stable/api/pipecat.services.elevenlabs.tts.html)
- [Pipecat src/services/tts_service.py — TTSService base + `run_tts`](https://raw.githubusercontent.com/pipecat-ai/pipecat/main/src/pipecat/services/tts_service.py) (run_tts at line 484)

---

## 9. Install + version

**Current version:** `pipecat-ai 1.3.0` (released 2026-05-28).

**Python:** `>=3.11` required; 3.12 recommended. SOVERYN's vnext venv runs `3.11+` per `pyproject.toml` — no upgrade needed.

**Install command (for Phase 1 — Aetheria, ElevenLabs HTTP, Silero VAD, browser WebRTC):**

```bash
pip install "pipecat-ai[silero,webrtc,elevenlabs]>=1.3.0,<2"
```

The voice-agent example pyproject.toml shows this exact pattern (their example uses `google` for the realtime LLM; we use `elevenlabs` for TTS — same `[option,option]` shape).

**What each extra pulls in:**
- `silero` — `onnxruntime` + the Silero VAD ONNX model weights (downloaded on first use).
- `webrtc` — `aiortc` (the Python-side WebRTC stack `SmallWebRTCTransport` uses under the hood) + supporting media libs.
- `elevenlabs` — `aiohttp` (if not already pulled) + ElevenLabs API helpers.

**System-level dependencies to verify on SOVERYN:**
- `aiortc` on Linux typically wants `libffi-dev`, `libssl-dev`, `libsrtp2-dev`, `libopus-dev`, `libvpx-dev`. These are likely already present on the Ubuntu reinstall (per `project_soveryn_reinstall_2026_04_27.md`), but Task 4 should `apt list --installed | grep -E 'srtp|opus|vpx|ffi'` and report missing deps before pipping.
- ONNX Runtime needs a GLIBC version that ships with Ubuntu 22.04+; SOVERYN is on a fresh reinstall so this is fine.
- No GPU dependency for VAD or transport — Silero VAD runs on CPU through ONNX Runtime by default. (We may want to investigate ONNX Runtime CUDA EP later for sub-ms VAD if it ever becomes a bottleneck, but the default CPU mode is fine for desk-level conversation.)

**The voice-agent example's full transitive deps for reference:**
- `python-dotenv`
- `fastapi[all]`
- `uvicorn`
- `pipecat-ai[google, silero, webrtc]>=1.3.0` (replace `google` with `elevenlabs` for us)

**Citations:**
- [pipecat-ai on PyPI](https://pypi.org/project/pipecat-ai/)
- [pipecat-examples voice-agent pyproject.toml](https://github.com/pipecat-ai/pipecat-examples/blob/main/p2p-webrtc/voice-agent/pyproject.toml)
- [Pipecat CHANGELOG 1.3.0 (transformers dropped from base deps)](https://github.com/pipecat-ai/pipecat/blob/main/CHANGELOG.md)

---

## 10. Concrete Phase 1 starting code

Skeleton for `soveryn/platform/voice/pipeline.py`. Task 4's implementer fills in the bridge body using the patterns in Q5 and the Parakeet wrapper from Q6. The shape is verified against the official p2p-webrtc voice-agent example.

```python
# soveryn/platform/voice/pipeline.py
"""Pipecat-based voice pipeline factory — Phase 1 (Aetheria, ElevenLabs).

Architecture (verified via pipecat 1.3.0 spike, 2026-06-10):

    browser mic
        |
    SmallWebRTCTransport.input()
        | AudioRawFrame
    SileroVADAnalyzer  (in TransportParams, emits VAD*SpeakingFrames)
        |
    ParakeetSTTService (SegmentedSTTService subclass — Q6)
        | TranscriptionFrame (finalized=True)
    AgentLoopBridge   (FrameProcessor — Q5)
        | LLMFullResponseStartFrame, LLMTextFrame*, LLMFullResponseEndFrame
    ElevenLabsHttpTTSService  (Pipecat built-in — Q7)
        | TTSAudioRawFrame
    SmallWebRTCTransport.output()
        |
    browser speakers

Interruption: when SileroVAD detects user speech mid-bot-talk, the transport
emits StartInterruptionFrame downstream. AgentLoopBridge cancels its in-flight
AgentLoop generator; TTS drops pending audio. See Q3.
"""

from __future__ import annotations

import asyncio
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
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.elevenlabs.tts import ElevenLabsHttpTTSService
from pipecat.services.stt_service import SegmentedSTTService
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.utils.time import time_now_iso8601
from pipecat.workers.runner import WorkerRunner

from soveryn.agents.loop import AgentLoop  # Task 4 step 2 also adds TTSTokenEvent
from soveryn.platform.voice.sanitize import sanitize_for_tts


# --------------------------------------------------------------------------
# Custom STT — Parakeet HTTP wrapper (Q6)
# --------------------------------------------------------------------------

class ParakeetSTTService(SegmentedSTTService):
    """SOVERYN Parakeet HTTP wrapper. VAD-bounded segments only."""

    def __init__(
        self,
        *,
        url: str = "http://127.0.0.1:8087",
        sample_rate: int = 16000,
        aiohttp_session: aiohttp.ClientSession | None = None,
        **kwargs: Any,
    ):
        super().__init__(sample_rate=sample_rate, **kwargs)
        self._url = url.rstrip("/") + "/transcribe"
        self._aiohttp_session = aiohttp_session

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame | None, None]:
        if not audio:
            return
        if self._aiohttp_session is None:
            self._aiohttp_session = aiohttp.ClientSession()
        async with self._aiohttp_session.post(
            self._url,
            data=audio,
            headers={"Content-Type": "audio/wav"},
            timeout=aiohttp.ClientTimeout(total=10.0),
        ) as response:
            if response.status != 200:
                return
            payload = await response.json()
            text = (payload.get("text") or "").strip()
            if text:
                yield TranscriptionFrame(
                    text=text,
                    user_id=self._user_id,
                    timestamp=time_now_iso8601(),
                )


# --------------------------------------------------------------------------
# AgentLoop bridge — FrameProcessor (Q5)
# --------------------------------------------------------------------------

class AgentLoopBridge(FrameProcessor):
    """Bridges Pipecat <-> AgentLoop.process_message_stream.

    Consumes TranscriptionFrame (finalized utterance) and emits
    LLMFullResponseStartFrame -> LLMTextFrame* -> LLMFullResponseEndFrame.

    Cancels in-flight AgentLoop generator on InterruptionFrame.
    """

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
            text = frame.text.strip()
            if text:
                await self._cancel_inflight()
                self._inflight_task = asyncio.create_task(self._run_turn(text))
            return
        await self.push_frame(frame, direction)

    async def _cancel_inflight(self):
        if self._inflight_task and not self._inflight_task.done():
            self._inflight_task.cancel()
            try:
                await self._inflight_task
            except BaseException:
                pass
        self._inflight_task = None

    async def _run_turn(self, user_text: str):
        await self.push_frame(LLMFullResponseStartFrame())
        try:
            async for event in self._agent_loop.process_message_stream(
                session_id=self._session_id, message=user_text,
            ):
                # TTSTokenEvent is added to loop.py in Task 4 step 2
                if event.__class__.__name__ == "TTSTokenEvent":
                    chunk = sanitize_for_tts(event.text)
                    if chunk:
                        await self.push_frame(LLMTextFrame(text=chunk))
        except asyncio.CancelledError:
            raise
        finally:
            await self.push_frame(LLMFullResponseEndFrame())


# --------------------------------------------------------------------------
# Pipeline factory (Q1)
# --------------------------------------------------------------------------

async def run_aetheria_voice_session(
    *,
    webrtc_connection: SmallWebRTCConnection,
    agent_loop: AgentLoop,
    session_id: str,
    elevenlabs_api_key: str,
    elevenlabs_voice_id: str,
    parakeet_url: str = "http://127.0.0.1:8087",
    aiohttp_session: aiohttp.ClientSession | None = None,
) -> None:
    """Run one voice session end-to-end. Returns when the client disconnects.

    Called from the /voice/<agent>/offer Flask/FastAPI endpoint after
    SmallWebRTCRequestHandler hands us a connection.
    """
    if aiohttp_session is None:
        aiohttp_session = aiohttp.ClientSession()

    transport = SmallWebRTCTransport(
        webrtc_connection=webrtc_connection,
        params=TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_out_10ms_chunks=2,
            vad_analyzer=SileroVADAnalyzer(
                sample_rate=16000,
                params=VADParams(confidence=0.7, start_secs=0.2, stop_secs=0.3),
            ),
        ),
    )

    stt = ParakeetSTTService(
        url=parakeet_url,
        sample_rate=16000,
        aiohttp_session=aiohttp_session,
    )

    bridge = AgentLoopBridge(agent_loop=agent_loop, session_id=session_id)

    tts = ElevenLabsHttpTTSService(
        api_key=elevenlabs_api_key,
        voice_id=elevenlabs_voice_id,
        aiohttp_session=aiohttp_session,
    )

    pipeline = Pipeline([
        transport.input(),
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
    async def on_disconnected(t, client):
        await worker.cancel()

    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    await runner.run()
```

**What's deliberately left to the Task 4 implementer:**
1. Wiring `TTSTokenEvent` into `AgentLoop.process_message_stream`. The bridge here uses `__name__` string-matching as a placeholder to avoid the import dependency in this skeleton; the implementer should import the real class once it lands and `isinstance`-check it. Spec'd in plan Task 4 step 2.
2. Choosing how the Flask blueprint hands a `SmallWebRTCConnection` to this factory. Either mount a FastAPI sub-app for `/voice/<agent>/offer` (recommended — pydantic typed request handler) or use `SmallWebRTCConnection` directly with a vanilla Flask JSON view. See Q4.
3. Telemetry plumbing — `enable_metrics=True` makes Pipecat emit `MetricsFrame`s; the Phase 3 telemetry task hooks `platform.telemetry` into a `MetricsObserver`. Phase 1 just turns it on.
4. Error/disconnect handling — the skeleton handles client disconnect; production-grade error frame routing (`ErrorFrame`, `on_connection_error`) is Phase 3 polish.

---

## 11. Surprises and follow-ups

- **`PipelineTask` → `PipelineWorker` rename (1.3.0)**. Plan-doc Task 4's commit message and the skeleton both reference the OLD name. Use `PipelineWorker` in the actual code. The old name still works with a `DeprecationWarning`, but starting on the deprecated symbol is silly when we're greenfield.
- **`PipelineRunner` → `WorkerRunner` (1.3.0)**. Same story.
- **`allow_interruptions` is being soft-deprecated in favor of "User Turn Strategies."** Phase 1 should still use `allow_interruptions=True` — the new strategies are richer (eager-end predictions, turn resumes) but documented as opt-in over the old default. Re-evaluate at Phase 3 when we have telemetry on how often Jon's interruptions catch Aetheria mid-word vs mid-thought.
- **SmallWebRTCTransport expects both audio AND video transceivers from the browser**, even for voice-only. The browser JS pattern from the official example does `pc.addTransceiver('video', { direction: 'sendrecv' })` with no video track. Don't strip this — leaving it out breaks negotiation.
- **The bridge sits OUTSIDE Pipecat's `LLMContextAggregatorPair` machinery on purpose.** AgentLoop owns context (lattice + conv_store). We deliberately don't use Pipecat's context aggregators because that would duplicate state and fight the abstraction. The voice path is a thin orchestrator over an already-stateful agent.
- **TTS provider abstraction (Task 3) is Phase-2-shaped, not Phase-1-required.** Phase 1's pipeline calls Pipecat's `ElevenLabsHttpTTSService` directly. The `TTSProvider` ABC and `ElevenLabsTTSProvider` from Task 3 sit alongside, ready to wrap a local TTS provider in Phase 2. This isn't a contradiction with the plan — Task 3 still ships clean; Phase 1's pipeline just doesn't route through it. Consider noting this in Task 3's commit message so the next reader understands the (mild) duplication.
- **One thing to double-check at integration time:** Pipecat's `EnvConfig` ABC for the LLM services normally expects an OpenAI-shaped API; we're skipping that whole layer with `AgentLoopBridge`. The pipeline-level `MetricsFrame` events (`enable_metrics=True`) typically come from `LLMService.start_llm_usage_metrics` etc. — our bridge won't emit them. Phase 3 telemetry should either add manual metrics emission from the bridge or accept the gap (it's just LLM-token-count telemetry that's missing; STT/TTS metrics still flow).

---

## 12. Bottom line

Pipecat 1.3.0 maps cleanly onto the architecture in the spec. SmallWebRTCTransport closes the only sovereignty risk (Q4) decisively. The bridge pattern between Pipecat's frame world and AgentLoop's event-stream world is a single ~60-line `FrameProcessor` (Q5). VAD, interruption, ElevenLabs TTS are built-in. Parakeet wrapping is `SegmentedSTTService` + `run_stt` override (~30 lines). The biggest unknown going into the spike — "does Pipecat work without Daily.co" — answers itself: every getting-started example uses SmallWebRTC, and Daily's own blog post is titled "You don't need a WebRTC server for your voice agents."

**Recommendation: proceed with Task 4 on Pipecat. No need to explore LiveKit.**

---

## Source links (consolidated)

- [Pipecat repo](https://github.com/pipecat-ai/pipecat)
- [Pipecat docs](https://docs.pipecat.ai/)
- [pipecat-ai on PyPI](https://pypi.org/project/pipecat-ai/)
- [Pipecat 1.3.0 CHANGELOG](https://github.com/pipecat-ai/pipecat/blob/main/CHANGELOG.md)
- [SmallWebRTCTransport docs](https://docs.pipecat.ai/server/services/transport/small-webrtc)
- [pipecat-examples voice-agent example](https://github.com/pipecat-ai/pipecat-examples/tree/main/p2p-webrtc/voice-agent)
- [SileroVADAnalyzer docs](https://docs.pipecat.ai/server/utilities/audio/silero-vad-analyzer)
- [SileroVADAnalyzer API reference](https://reference-server.pipecat.ai/en/stable/api/pipecat.audio.vad.silero.html)
- [STTService API reference](https://reference-server.pipecat.ai/en/stable/api/pipecat.services.stt_service.html)
- [ElevenLabs TTS service docs](https://docs.pipecat.ai/api-reference/server/services/tts/elevenlabs)
- [Pipeline & Frame Processing guide](https://docs.pipecat.ai/guides/learn/pipeline)
- [Daily blog — You don't need a WebRTC server](https://www.daily.co/blog/you-dont-need-a-webrtc-server-for-your-voice-agents/)
- [Anam — Frame processing in Pipecat](https://anam.ai/blog/pipecat-frame-processing-guide)
