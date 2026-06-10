# Sovereign Voice — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Scope:** Phase 1 only (Aetheria's voice through a modern Pipecat orchestrator, ElevenLabs still primary). Phases 1.5 / 2 / 3 from the spec get their own plans **after** Phase 1 ships — they depend on what Phase 1 teaches us about Pipecat behavior, audio latency on this hardware, and Vett/Scotty's voice choices landing.

**Goal:** Replace the patched ElevenLabs-cloud voice pipeline with a Pipecat-based voice agent for Aetheria. Continuous listening with VAD, interruption / barge-in, sanitization-at-source in AgentLoop, orb UI as Pipecat WebRTC client, twilight-violet color, `[voice]` session prefix into conv_store. No legacy code from `soveryn_complete/{voice.py,tts.py,sovereign_tts.py,core/voice_pipeline.py}` is ported.

**Architecture:** New `soveryn/platform/voice/` package with `config / providers / pipeline / sanitize` modules. New `soveryn/app/routes/voice.py` Flask blueprint serving `/voice/aetheria` (and the agent-picker landing at `/voice`). Pipecat is the orchestrator framework; Parakeet on `:8087` is STT (unchanged); ElevenLabs is the only TTS provider in Phase 1 (local TTS is Phase 2). AgentLoop grows a secondary "sanitized for TTS" output channel that strips thinking/markup/tool-calls before TTS sees the text.

**Tech Stack:** Python 3.10+, Pipecat (`pipecat-ai`), Silero VAD (Pipecat's bundled VAD processor), WebRTC (Pipecat's default browser transport), Parakeet HTTP on `:8087`, ElevenLabs REST API. No Daily.co cloud — single-user on `127.0.0.1` only.

**Spec:** `docs/superpowers/specs/2026-06-10-sovereign-voice-design.md`.

**Hard prerequisite:** Path consolidation shipped 2026-06-10 (commits d1d2ae2 → 1e816ac + maintenance-window execution). Voice asset paths in this plan reference `~/soveryn_vnext/data/voice/` as established by that build.

---

## Pipecat investigation spike (prerequisite, NOT a numbered task)

Before Task 1 dispatches: dispatch a research-only subagent to read Pipecat's current docs and validate the architecture works for SOVERYN. Findings drive the patterns Tasks 4-7 use.

**Deliverable:** a markdown writeup at `docs/superpowers/notes/2026-06-10-pipecat-spike.md` answering:

1. **API shape:** how to construct a Pipecat `Pipeline` with custom processors. Show the actual code for a minimal pipeline with: WebRTC transport → STT (custom HTTP to Parakeet) → user-text → LLM bridge (callable, our AgentLoop) → assistant-text → TTS (custom HTTP to ElevenLabs) → audio out → WebRTC transport.
2. **VAD:** does Pipecat ship a Silero VAD processor? What's the activation knob (probability threshold, silence duration)?
3. **Interruption / barge-in:** what's the contract for cancelling an in-flight LLM/TTS pipeline when VAD fires user speech mid-bot-talk? Code example.
4. **WebRTC for browser:** does Pipecat support browser-only WebRTC without Daily.co? If a Daily.co room is required even for local-only, that's a blocker; LiveKit Agents is the documented fallback.
5. **Streaming AgentLoop integration:** how does the LLM processor consume a Python iterator of text chunks (our `AgentLoop.process_message_stream` yields). Confirm the bridge shape.
6. **Custom STT processor:** what interface does the STT processor implement? Parakeet returns transcript on POST; we need to feed audio frames and surface text. Code example.
7. **Custom TTS processor:** same question — what interface? ElevenLabs streams audio chunks; we surface them.

**If Pipecat doesn't fit cleanly,** the writeup escalates: name the blocker, propose LiveKit Agents as alternative, and the controller pivots before Task 1 dispatches.

**Spike subagent prompt skeleton:** use the general-purpose agent with `WebFetch` access. Don't write SOVERYN code yet — just the investigation writeup.

---

## File Structure

**New files:**
- `soveryn/platform/voice/__init__.py` — package exports
- `soveryn/platform/voice/config.py` — `VoiceConfig` dataclass + env loading + per-agent voice ID lookup
- `soveryn/platform/voice/providers/__init__.py`
- `soveryn/platform/voice/providers/base.py` — `TTSProvider` abstract base + `TTSChunk` type
- `soveryn/platform/voice/providers/elevenlabs.py` — `ElevenLabsTTSProvider` implementation
- `soveryn/platform/voice/sanitize.py` — `sanitize_for_tts(text)` pure function + tests
- `soveryn/platform/voice/pipeline.py` — `build_aetheria_voice_pipeline(agent_loop, ...)` factory
- `soveryn/app/routes/voice.py` — Flask blueprint: `/voice` (agent picker) + `/voice/<agent>` (per-agent room)
- `soveryn/app/templates/voice.html` — orb UI as Pipecat WebRTC client (per-agent themed)
- `soveryn/app/static/voice/` — JS/CSS assets for the WebRTC client
- `tests/test_voice_config.py`
- `tests/test_voice_sanitize.py`
- `tests/test_voice_elevenlabs_provider.py`
- `tests/test_voice_pipeline_smoke.py` (integration-ish; may be marked slow)
- `docs/superpowers/notes/2026-06-10-pipecat-spike.md` — the spike writeup (prerequisite)

**Modified files:**
- `soveryn/config/loader.py` — add ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID_AETHERIA, voice_root path
- `soveryn/agents/loop.py` — emit sanitized TTS text channel in addition to full assistant content
- `soveryn/app/startup.py` — register voice blueprint, wire voice services Aetheria-only
- `pyproject.toml` — add `pipecat-ai` dependency (exact version from spike writeup)

**Not touched:**
- Any file in `~/soveryn_complete/`. Zero lift, zero patches.

---

## Task 1: Voice config in EnvConfig + voice config dataclass

**Files:**
- Create: `soveryn/platform/voice/__init__.py`
- Create: `soveryn/platform/voice/config.py`
- Create: `tests/test_voice_config.py`
- Modify: `soveryn/config/loader.py` — add three voice-related fields

Voice config layered as: secrets in EnvConfig (`ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID_AETHERIA`), per-agent voice character in `VoiceConfig` dataclass that gets passed into the pipeline factory.

- [ ] **Step 1: Tests for VoiceConfig + EnvConfig fields**

```python
# tests/test_voice_config.py
from pathlib import Path
from soveryn.platform.voice.config import (
    VoiceConfig, AgentVoiceCharacter, DEFAULT_VOICE_ROOT,
)
from soveryn.config.loader import load_env_config


def test_voice_config_for_aetheria_uses_env_voice_id():
    cfg = VoiceConfig.from_env({
        "ELEVENLABS_API_KEY": "test-key",
        "ELEVENLABS_VOICE_ID_AETHERIA": "voice-aetheria-id",
    })
    aetheria = cfg.agent_character("aetheria")
    assert aetheria.elevenlabs_voice_id == "voice-aetheria-id"


def test_voice_config_returns_none_for_unconfigured_agent():
    cfg = VoiceConfig.from_env({"ELEVENLABS_API_KEY": "key"})
    assert cfg.agent_character("scotty") is None  # not yet configured in Phase 1


def test_env_config_has_voice_fields():
    cfg = load_env_config({
        "ELEVENLABS_API_KEY": "k",
        "ELEVENLABS_VOICE_ID_AETHERIA": "va",
    })
    assert cfg.elevenlabs_api_key == "k"
    assert cfg.elevenlabs_voice_id_aetheria == "va"
    assert cfg.voice_root == cfg.data_root / "voice"


def test_voice_root_derives_from_data_root_cascade():
    cfg = load_env_config({"SOVERYN_DATA_ROOT": "/tmp/custom"})
    assert cfg.voice_root == Path("/tmp/custom/voice")


def test_voice_root_explicit_env_override_wins():
    cfg = load_env_config({"SOVERYN_VOICE_ROOT": "/other/voice/path"})
    assert cfg.voice_root == Path("/other/voice/path")
```

- [ ] **Step 2: Implement config.py**

```python
# soveryn/platform/voice/config.py
"""Voice config — per-agent voice characters + EnvConfig integration.

Phase 1: Aetheria only (ElevenLabs cloud). Phases 1.5/2 extend this
shape to include Vett and Scotty + local TTS providers."""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path


DEFAULT_VOICE_ROOT_NAME = "voice"  # under data_root


@dataclass(frozen=True)
class AgentVoiceCharacter:
    """A single agent's voice character config."""
    agent_name: str
    elevenlabs_voice_id: str | None  # None when not configured for ElevenLabs


@dataclass(frozen=True)
class VoiceConfig:
    """Voice config for the fleet. Phase 1: Aetheria only."""
    elevenlabs_api_key: str | None
    aetheria_voice_id: str | None
    # Phase 1.5 adds vett_voice_id, scotty_voice_id when their characters land

    @classmethod
    def from_env(cls, env: dict[str, str]) -> "VoiceConfig":
        return cls(
            elevenlabs_api_key=env.get("ELEVENLABS_API_KEY") or None,
            aetheria_voice_id=env.get("ELEVENLABS_VOICE_ID_AETHERIA") or None,
        )

    def agent_character(self, agent_name: str) -> AgentVoiceCharacter | None:
        agent_name = agent_name.lower().strip()
        if agent_name == "aetheria":
            if self.elevenlabs_api_key is None or self.aetheria_voice_id is None:
                return None
            return AgentVoiceCharacter(
                agent_name="aetheria",
                elevenlabs_voice_id=self.aetheria_voice_id,
            )
        # Phase 1.5 will return characters for vett + scotty
        return None
```

- [ ] **Step 3: Implement __init__.py**

```python
# soveryn/platform/voice/__init__.py
"""Sovereign voice — Pipecat-based voice agent for SOVERYN.

Phase 1: Aetheria on ElevenLabs through a modern orchestrator with
VAD-based continuous listening + interruption + sanitization-at-source.
Replaces the patched cloud pipeline from soveryn_complete.

See docs/superpowers/specs/2026-06-10-sovereign-voice-design.md."""

from soveryn.platform.voice.config import (
    AgentVoiceCharacter,
    DEFAULT_VOICE_ROOT_NAME,
    VoiceConfig,
)

__all__ = [
    "AgentVoiceCharacter",
    "DEFAULT_VOICE_ROOT_NAME",
    "VoiceConfig",
]
```

- [ ] **Step 4: Add voice fields to EnvConfig**

In `soveryn/config/loader.py`:

```python
# At the top, alongside other DEFAULT_* helpers:
def _default_voice_root(root: Path) -> Path:
    return root / "voice"

# In EnvConfig dataclass, after cross_surface_* fields:
elevenlabs_api_key: str | None
elevenlabs_voice_id_aetheria: str | None
voice_root: Path

# In load_env_config(), after data_root resolution:
return EnvConfig(
    # ... existing fields ...
    elevenlabs_api_key=env.get("ELEVENLABS_API_KEY") or None,
    elevenlabs_voice_id_aetheria=env.get("ELEVENLABS_VOICE_ID_AETHERIA") or None,
    voice_root=_parse_path("SOVERYN_VOICE_ROOT", env.get("SOVERYN_VOICE_ROOT"),
                          default=_default_voice_root(data_root)),
)
```

Update `_env()` test helper in `tests/test_launcher.py` with the new fields (defaults `None, None, /tmp/test-voice`).

- [ ] **Step 5: Tests pass + global pytest stays green**

- [ ] **Step 6: Commit**

```
feat(voice): config + ElevenLabs secrets in EnvConfig

VoiceConfig dataclass with per-agent character lookup (Phase 1: aetheria
only). EnvConfig gains elevenlabs_api_key, elevenlabs_voice_id_aetheria,
voice_root (derived off data_root with env override). No pipeline code
yet.
```

Author: `jdeoliveira@soverynintelligence.com`.

---

## Task 2: Sanitization-at-source (`sanitize_for_tts`)

**Files:**
- Create: `soveryn/platform/voice/sanitize.py`
- Create: `tests/test_voice_sanitize.py`

Pure function. Takes raw assistant text (may contain `<think>...</think>`, tool-call JSON, scratchpad tags, control tokens) and returns clean text suitable for TTS. The spec is explicit: **filter at source, not as a downstream cascade.** Single function, single boundary, well-tested.

- [ ] **Step 1: Tests**

```python
# tests/test_voice_sanitize.py
from soveryn.platform.voice.sanitize import sanitize_for_tts


def test_strips_think_tags():
    raw = "<think>weighing this</think>The answer is forty-two."
    assert sanitize_for_tts(raw) == "The answer is forty-two."


def test_strips_nested_think_tags():
    raw = "<think>outer<think>inner</think>more outer</think>Hi."
    assert sanitize_for_tts(raw) == "Hi."


def test_strips_unclosed_think_tag_safely():
    raw = "<think>this should be dropped if no closer"
    # When a think tag opens but never closes, drop from the tag onward
    assert sanitize_for_tts(raw) == ""


def test_strips_tool_call_json():
    raw = '<tool_call>{"name":"x","args":{}}</tool_call>What I found:'
    assert sanitize_for_tts(raw) == "What I found:"


def test_strips_scratchpad_tags():
    raw = "[SCRATCHPAD: thinking aloud]\nThe call is locked."
    assert "SCRATCHPAD" not in sanitize_for_tts(raw)


def test_strips_resolve_defer_tags():
    raw = "[RESOLVE: yes] The migration shipped. [DEFER: next steps]"
    out = sanitize_for_tts(raw)
    assert "RESOLVE" not in out
    assert "DEFER" not in out
    assert "The migration shipped." in out


def test_collapses_excessive_whitespace():
    raw = "Hello   \n\n\nworld."
    out = sanitize_for_tts(raw)
    assert "   " not in out
    assert "\n\n\n" not in out


def test_strips_control_tokens():
    raw = "<|im_start|>hi<|im_end|> and hello."
    out = sanitize_for_tts(raw)
    assert "<|" not in out
    assert "|>" not in out


def test_preserves_natural_punctuation():
    """Sentence-ending punctuation matters for TTS prosody — don't strip it."""
    raw = "First. Second! Third? Yes."
    out = sanitize_for_tts(raw)
    assert "." in out
    assert "!" in out
    assert "?" in out


def test_empty_input_returns_empty():
    assert sanitize_for_tts("") == ""
    assert sanitize_for_tts("   ") == ""


def test_idempotent():
    raw = "<think>x</think>Hello."
    once = sanitize_for_tts(raw)
    twice = sanitize_for_tts(once)
    assert once == twice


def test_strips_heartbeat_markup():
    """[HEARTBEAT] and similar daemon-scoped markup shouldn't appear in TTS."""
    raw = "[HEARTBEAT 30min ago] Anything to act on?"
    out = sanitize_for_tts(raw)
    assert "[HEARTBEAT" not in out


def test_strips_emoji_that_break_prosody():
    """Emoji throw TTS prosody; strip them. Letters/punctuation stay."""
    raw = "Done ✓ ✨ — ready."
    out = sanitize_for_tts(raw)
    # We'd accept either fully stripped or replaced; the test passes as long
    # as no emoji chars remain
    assert "✓" not in out
    assert "✨" not in out
    assert "ready" in out
```

- [ ] **Step 2: Implement sanitize.py**

```python
# soveryn/platform/voice/sanitize.py
"""Sanitize assistant text for TTS at source.

Single function, single boundary. Replaces the accumulated filter chain
from the legacy voice pipeline (project_soveryn_voice_pipeline.md notes
the chain that grew over months of patches)."""

from __future__ import annotations
import re
import unicodedata


# Compiled once for performance
_RE_THINK_TAG = re.compile(r"<think\b[^>]*>.*?(?:</think>|$)", re.DOTALL | re.IGNORECASE)
_RE_TOOL_CALL = re.compile(r"<tool_call\b[^>]*>.*?</tool_call>", re.DOTALL | re.IGNORECASE)
_RE_BRACKET_TAG = re.compile(
    r"\[(SCRATCHPAD|RESOLVE|DEFER|HEARTBEAT|TOOL|SYSTEM)[^\]]*\]\s*\n?",
    re.IGNORECASE,
)
_RE_CONTROL_TOKEN = re.compile(r"<\|[^|]*\|>")
_RE_WHITESPACE = re.compile(r"\s+")


def sanitize_for_tts(text: str) -> str:
    """Strip thinking markup, control tokens, tool-call JSON, scratchpad
    tags, and emoji from `text`. Return clean prose for TTS.
    
    Idempotent. Empty input → empty output. Preserves sentence-ending
    punctuation (matters for TTS prosody)."""
    if not text:
        return ""
    
    # 1. Drop think tags (handle unclosed safely via DOTALL + alternation)
    # The pattern matches <think>...</think> OR <think>...EOF
    text = _RE_THINK_TAG.sub("", text)
    
    # 2. Drop tool-call JSON
    text = _RE_TOOL_CALL.sub("", text)
    
    # 3. Drop bracketed daemon/control tags
    text = _RE_BRACKET_TAG.sub("", text)
    
    # 4. Drop control tokens like <|im_start|>
    text = _RE_CONTROL_TOKEN.sub("", text)
    
    # 5. Drop emoji (any char with Symbol or Symbol-Other unicode category)
    text = "".join(c for c in text if unicodedata.category(c)[0] != "S")
    
    # 6. Collapse whitespace runs to single space
    text = _RE_WHITESPACE.sub(" ", text).strip()
    
    return text
```

- [ ] **Step 3: Tests pass**

- [ ] **Step 4: Commit**

```
feat(voice): sanitize_for_tts — single boundary, no filter cascade

Pure function: assistant text → clean prose for TTS. Strips think tags,
tool-call JSON, scratchpad/daemon markup, control tokens, emoji.
Idempotent. Preserves sentence-ending punctuation for prosody.
```

---

## Task 3: TTS provider interface + ElevenLabs implementation

**Files:**
- Create: `soveryn/platform/voice/providers/__init__.py`
- Create: `soveryn/platform/voice/providers/base.py`
- Create: `soveryn/platform/voice/providers/elevenlabs.py`
- Create: `tests/test_voice_elevenlabs_provider.py`

Abstract `TTSProvider` base + `ElevenLabsTTSProvider` HTTP client. Phase 2 adds `LocalTTSProvider` via the same interface; the orchestrator doesn't care which.

- [ ] **Step 1: Define the base interface**

```python
# soveryn/platform/voice/providers/base.py
"""TTS provider interface — abstract base.

Phase 1: ElevenLabs implementation. Phase 2: LocalTTSProvider via same
interface so the pipeline doesn't change."""

from __future__ import annotations
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass


@dataclass(frozen=True)
class TTSChunk:
    """A chunk of synthesized audio."""
    audio_bytes: bytes
    sample_rate: int
    is_final: bool  # True when this is the last chunk for this utterance


class TTSError(Exception):
    """Raised when TTS synthesis fails. Pipeline should fall back to next
    provider or surface a user-facing error."""


class TTSProvider(ABC):
    """Abstract TTS provider.
    
    `synthesize(text)` is an async generator yielding TTSChunk instances.
    Streaming providers (ElevenLabs WebSocket) yield as audio arrives;
    non-streaming providers yield a single chunk with is_final=True."""

    @abstractmethod
    async def synthesize(self, text: str, *, voice_id: str) -> AsyncIterator[TTSChunk]:
        """Synthesize `text` using `voice_id`. Yield audio chunks."""
        ...
        # Note: implementations are async generators; this signature is for the contract.

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name for logging/telemetry."""
        ...
```

- [ ] **Step 2: Implement ElevenLabs provider**

```python
# soveryn/platform/voice/providers/elevenlabs.py
"""ElevenLabs TTS provider — REST API call with streaming response.

ElevenLabs supports streaming via /v1/text-to-speech/{voice_id}/stream.
We POST text + model_id + voice_settings, receive a chunked audio stream
back, yield as TTSChunks."""

from __future__ import annotations
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from soveryn.platform.voice.providers.base import TTSChunk, TTSError, TTSProvider


logger = logging.getLogger(__name__)

ELEVENLABS_STREAM_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
DEFAULT_MODEL_ID = "eleven_turbo_v2_5"
DEFAULT_SAMPLE_RATE = 22050
CHUNK_SIZE_BYTES = 4096


class ElevenLabsTTSProvider(TTSProvider):
    """HTTP streaming client for ElevenLabs TTS."""

    def __init__(
        self,
        *,
        api_key: str,
        model_id: str = DEFAULT_MODEL_ID,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        # Injectable for tests
        http_client: Any | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key required")
        self.api_key = api_key
        self.model_id = model_id
        self.sample_rate = sample_rate
        # If a test injects a fake httpx.AsyncClient, use it; otherwise
        # the real one is constructed lazily on first call (to keep import
        # surface lean — httpx is a heavy dep)
        self._http_client = http_client

    @property
    def name(self) -> str:
        return "elevenlabs"

    async def synthesize(
        self, text: str, *, voice_id: str,
    ) -> AsyncIterator[TTSChunk]:
        if not text.strip():
            return
        if self._http_client is None:
            import httpx
            self._http_client = httpx.AsyncClient(timeout=60.0)

        url = ELEVENLABS_STREAM_URL.format(voice_id=voice_id)
        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",  # or 'audio/pcm' depending on format support
        }
        body = {
            "text": text,
            "model_id": self.model_id,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.8,
            },
        }

        try:
            async with self._http_client.stream(
                "POST", url, headers=headers, json=body,
            ) as response:
                if response.status_code != 200:
                    err_body = await response.aread()
                    raise TTSError(
                        f"ElevenLabs returned {response.status_code}: {err_body[:200]!r}"
                    )
                async for chunk_bytes in response.aiter_bytes(chunk_size=CHUNK_SIZE_BYTES):
                    if chunk_bytes:
                        yield TTSChunk(
                            audio_bytes=chunk_bytes,
                            sample_rate=self.sample_rate,
                            is_final=False,
                        )
            # End of stream — emit final marker
            yield TTSChunk(audio_bytes=b"", sample_rate=self.sample_rate, is_final=True)
        except Exception as e:
            if isinstance(e, TTSError):
                raise
            raise TTSError(f"ElevenLabs synthesis failed: {type(e).__name__}: {e}") from e
```

- [ ] **Step 3: Tests using mocked HTTP**

```python
# tests/test_voice_elevenlabs_provider.py
import pytest
from soveryn.platform.voice.providers.elevenlabs import (
    ElevenLabsTTSProvider, ELEVENLABS_STREAM_URL,
)
from soveryn.platform.voice.providers.base import TTSChunk, TTSError


class FakeAsyncStreamingResponse:
    def __init__(self, status_code, chunks):
        self.status_code = status_code
        self._chunks = chunks

    async def aiter_bytes(self, chunk_size):
        for c in self._chunks:
            yield c

    async def aread(self):
        return b"".join(self._chunks)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pass


class FakeHTTPClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def stream(self, method, url, headers, json):
        self.calls.append({"method": method, "url": url, "headers": headers, "json": json})
        return self.response


@pytest.mark.asyncio
async def test_synthesize_yields_audio_chunks():
    fake_response = FakeAsyncStreamingResponse(200, [b"abc", b"def"])
    fake_http = FakeHTTPClient(fake_response)
    provider = ElevenLabsTTSProvider(api_key="k", http_client=fake_http)
    chunks = []
    async for chunk in provider.synthesize("hello", voice_id="voice-1"):
        chunks.append(chunk)
    # Two audio chunks + one final-marker chunk
    assert len(chunks) == 3
    assert chunks[0].audio_bytes == b"abc"
    assert chunks[1].audio_bytes == b"def"
    assert chunks[2].is_final is True


@pytest.mark.asyncio
async def test_synthesize_uses_correct_voice_id_in_url():
    fake_response = FakeAsyncStreamingResponse(200, [b"audio"])
    fake_http = FakeHTTPClient(fake_response)
    provider = ElevenLabsTTSProvider(api_key="k", http_client=fake_http)
    async for _ in provider.synthesize("hi", voice_id="my-voice-xyz"):
        pass
    assert "my-voice-xyz" in fake_http.calls[0]["url"]


@pytest.mark.asyncio
async def test_synthesize_raises_on_error_status():
    fake_response = FakeAsyncStreamingResponse(429, [b'{"error":"rate limit"}'])
    fake_http = FakeHTTPClient(fake_response)
    provider = ElevenLabsTTSProvider(api_key="k", http_client=fake_http)
    with pytest.raises(TTSError, match="429"):
        async for _ in provider.synthesize("hi", voice_id="v"):
            pass


@pytest.mark.asyncio
async def test_synthesize_empty_text_yields_nothing():
    fake_response = FakeAsyncStreamingResponse(200, [b"audio"])
    fake_http = FakeHTTPClient(fake_response)
    provider = ElevenLabsTTSProvider(api_key="k", http_client=fake_http)
    chunks = []
    async for chunk in provider.synthesize("   ", voice_id="v"):
        chunks.append(chunk)
    assert chunks == []
    assert fake_http.calls == []  # never called the API


def test_constructor_rejects_empty_api_key():
    with pytest.raises(ValueError, match="api_key"):
        ElevenLabsTTSProvider(api_key="")


def test_name_is_elevenlabs():
    provider = ElevenLabsTTSProvider(api_key="k")
    assert provider.name == "elevenlabs"
```

- [ ] **Step 4: Tests pass**

- [ ] **Step 5: Commit**

```
feat(voice): TTSProvider interface + ElevenLabs streaming implementation

Abstract TTSProvider base; ElevenLabsTTSProvider posts to
/v1/text-to-speech/{voice_id}/stream and yields TTSChunks as audio
arrives. Phase 2 LocalTTSProvider will implement the same interface.
```

---

## Task 4: Voice pipeline (Pipecat orchestrator)

**Files:**
- Create: `soveryn/platform/voice/pipeline.py`
- Create: `tests/test_voice_pipeline_smoke.py` (integration-ish)
- Modify: `pyproject.toml` — add `pipecat-ai` dependency (exact version from spike writeup)
- Modify: `soveryn/agents/loop.py` — add sanitized TTS text channel to streaming output

**This is the largest task.** Depends entirely on Pipecat spike findings. Specific code below is a starting shape — implementer adjusts based on actual Pipecat API.

- [ ] **Step 1: Add Pipecat dependency**

Read `pyproject.toml`. Add `pipecat-ai = "^X.Y.Z"` (version from spike) to `[project.dependencies]` or wherever existing deps live. Run `pip install -e .` (or however vnext is installed) in the conda env to pick it up.

- [ ] **Step 2: Add TTS channel to AgentLoop streaming**

`AgentLoop.process_message_stream` currently yields chunks of the assistant content. The voice pipeline needs a parallel stream of SANITIZED text suitable for TTS — same content, filter applied before each chunk emits.

```python
# In soveryn/agents/loop.py — sketch (verify against actual streaming shape)
from soveryn.platform.voice.sanitize import sanitize_for_tts

# Existing streaming path yields DoneEvent and TokenEvents (or whatever the
# current shape is). Add a TTSTokenEvent class:

@dataclass(frozen=True)
class TTSTokenEvent:
    """Sanitized assistant text fragment for TTS consumption.
    Emitted in parallel with regular token events; carries only the
    sanitized content (no thinking, no markup, no control tokens)."""
    text: str


# In the streaming loop, AFTER assembling each text chunk for the regular
# stream, ALSO sanitize and emit as TTSTokenEvent:
#   yield TokenEvent(text=raw_chunk)
#   sanitized = sanitize_for_tts(raw_chunk)
#   if sanitized:
#       yield TTSTokenEvent(text=sanitized)
```

The voice pipeline subscribes to TTSTokenEvents only; the chat UI subscribes to TokenEvents only. Same generator, two views.

- [ ] **Step 3: Build the Pipecat pipeline factory**

```python
# soveryn/platform/voice/pipeline.py
"""Pipecat-based voice pipeline factory.

Constructs a pipeline:
  WebRTC (browser) → STT (Parakeet HTTP) → user text
    → AgentLoop bridge → assistant TTS text channel
      → TTS provider → audio chunks → WebRTC (browser)

VAD-based continuous listening + interruption / barge-in are upstream
concerns Pipecat handles. We provide the SOVERYN-specific bridges:
Parakeet HTTP wrapper, AgentLoop bridge (calls process_message_stream
and subscribes to TTSTokenEvents), TTS provider invocation."""

from __future__ import annotations

# Pipecat imports — exact names from spike writeup
# from pipecat.pipeline.pipeline import Pipeline
# from pipecat.pipeline.task import PipelineTask
# from pipecat.processors.frame_processor import FrameProcessor
# from pipecat.frames.frames import TextFrame, AudioRawFrame, UserStartedSpeakingFrame
# from pipecat.transports.network.webrtc import WebRTCTransport
# from pipecat.vad.silero import SileroVAD

# SOVERYN imports
from soveryn.agents.loop import AgentLoop
from soveryn.platform.voice.providers.base import TTSProvider
from soveryn.platform.voice.providers.elevenlabs import ElevenLabsTTSProvider


# Implementation skeleton — concrete code from spike writeup
def build_aetheria_voice_pipeline(
    *,
    agent_loop: AgentLoop,
    voice_id: str,
    tts_provider: TTSProvider,
    parakeet_url: str = "http://127.0.0.1:8087",
):
    """Build a Pipecat pipeline for an Aetheria voice session.
    
    Returns a pipeline + task pair ready for the Flask blueprint to drive."""
    # Construct WebRTC transport, VAD processor, STT processor (Parakeet),
    # AgentLoop bridge (subscribes to TTSTokenEvents from process_message_stream),
    # TTS processor (calls tts_provider.synthesize), audio output back to WebRTC.
    # 
    # IMPLEMENTER: fill in based on spike writeup. The spike confirms the exact
    # Pipecat patterns; this skeleton is the architectural shape only.
    raise NotImplementedError("Implementation depends on spike findings")
```

- [ ] **Step 4: Implementation work**

Implementer constructs the actual pipeline per the spike writeup. Each component (STT, VAD, LLM bridge, TTS) becomes a Pipecat FrameProcessor or uses Pipecat's bundled versions where available. Aim for the smallest-possible-pipeline that works; we'll optimize in Phase 3.

- [ ] **Step 5: Smoke test the pipeline factory**

The full pipeline needs a browser to test end-to-end. For the smoke test: construct the pipeline factory, assert the components are wired (transport exists, VAD enabled, TTS provider wired, AgentLoop reference held). Live verification happens in Task 8.

- [ ] **Step 6: Commit**

```
feat(voice): Pipecat orchestrator for Aetheria voice

Pipeline factory + AgentLoop sanitized TTS channel + Pipecat
WebRTC/VAD/STT/TTS processors wired. Continuous listening,
interruption, barge-in inherited from Pipecat. Implementation details
guided by docs/superpowers/notes/2026-06-10-pipecat-spike.md.
```

---

## Task 5: Flask blueprint `/voice/aetheria`

**Files:**
- Create: `soveryn/app/routes/voice.py`
- Tests: extend `tests/test_app_ui_compat_routes.py` or new test file

Blueprint serves:
- `GET /voice` — agent picker landing page (Phase 1 just shows Aetheria; future agents added in Phase 1.5)
- `GET /voice/<agent>` — agent's voice room page (orb UI + Pipecat client)
- `POST /voice/<agent>/offer` — WebRTC signaling: receives browser SDP offer, returns answer
- (and any other Pipecat-required signaling endpoints from the spike)

- [ ] **Step 1: Implement the blueprint**

```python
# soveryn/app/routes/voice.py
"""Voice blueprint — /voice and /voice/<agent> with Pipecat WebRTC bridge."""

from __future__ import annotations

from flask import Blueprint, render_template, jsonify, request, abort


bp = Blueprint("voice", __name__)
SUPPORTED_AGENTS = ("aetheria",)  # Phase 1.5 adds vett + scotty


@bp.get("/voice")
def voice_landing():
    return render_template("voice_landing.html", agents=SUPPORTED_AGENTS)


@bp.get("/voice/<agent>")
def voice_room(agent: str):
    agent = agent.lower().strip()
    if agent not in SUPPORTED_AGENTS:
        abort(404, f"voice not yet configured for agent {agent!r}")
    return render_template("voice.html", agent=agent)


@bp.post("/voice/<agent>/offer")
def voice_offer(agent: str):
    """WebRTC SDP offer — browser sends offer, we return answer."""
    agent = agent.lower().strip()
    if agent not in SUPPORTED_AGENTS:
        abort(404)
    body = request.get_json(silent=True) or {}
    # Hand off to Pipecat to negotiate SDP — implementation per spike writeup
    # answer = run_pipeline_for_session(agent, sdp=body["sdp"], ...)
    # return jsonify({"answer": answer})
    raise NotImplementedError("WebRTC bridge per spike writeup")
```

- [ ] **Step 2: Wire into startup.py**

```python
# In soveryn/app/startup.py
from soveryn.app.routes import voice as voice_routes
app.register_blueprint(voice_routes.bp)
```

- [ ] **Step 3: Tests**

```python
# tests/test_voice_routes.py
def test_voice_landing_lists_aetheria(client):
    rv = client.get("/voice")
    assert rv.status_code == 200
    assert b"aetheria" in rv.data.lower()


def test_voice_room_for_aetheria_renders():
    # ... (returns 200 with the orb UI)


def test_voice_room_for_unconfigured_agent_404s(client):
    rv = client.get("/voice/vett")
    assert rv.status_code == 404


def test_voice_room_for_specialist_or_daemon_404s(client):
    """Aetheria-only in Phase 1."""
    rv = client.get("/voice/heartbeat")
    assert rv.status_code == 404
```

- [ ] **Step 4: Commit**

```
feat(voice): /voice landing + /voice/aetheria Flask blueprint

Aetheria-only in Phase 1. Phase 1.5 expands SUPPORTED_AGENTS to
include vett + scotty as their voice characters land.
```

---

## Task 6: Orb UI as Pipecat client

**Files:**
- Create: `soveryn/app/templates/voice.html`
- Create: `soveryn/app/templates/voice_landing.html`
- Create: `soveryn/app/static/voice/orb.css` (twilight-violet styling)
- Create: `soveryn/app/static/voice/voice_client.js` (Pipecat WebRTC client)

The orb UI gets rebuilt — same visual character (twilight-violet for Aetheria), new state machine (listening / hearing speech / thinking / speaking / interrupted), Pipecat WebRTC handshake.

- [ ] **Step 1: Build voice_landing.html**

Simple page: list of available agents as orb thumbnails, click to enter a voice room. Phase 1 only Aetheria visible; Phase 1.5 grows the list.

- [ ] **Step 2: Build voice.html as the Pipecat client**

Template variables: `{{ agent }}` (used to fetch agent-specific config + color theme). JS sets up WebRTC, POSTs to `/voice/<agent>/offer`, renders the orb with state transitions driven by Pipecat's frame events arriving over the datachannel.

- [ ] **Step 3: orb.css with per-agent color themes**

CSS custom properties (`--orb-color-primary`, `--orb-color-secondary`) defined per agent class. Aetheria: twilight-violet `#5d3a8e` / `#8e6ec4`. Phase 1.5 adds Vett's color, Scotty's color.

- [ ] **Step 4: voice_client.js — WebRTC + state machine**

Sketch:

```javascript
// /static/voice/voice_client.js
const agent = document.body.dataset.agent;
const orb = document.getElementById("orb");

const STATES = {
    IDLE: "idle",
    LISTENING: "listening",
    HEARING: "hearing",
    THINKING: "thinking",
    SPEAKING: "speaking",
    INTERRUPTED: "interrupted",
};

function setState(state) {
    orb.dataset.state = state;
}

async function connect() {
    const pc = new RTCPeerConnection();
    // Add mic, set up data channel for Pipecat events, exchange SDP
    // (exact pattern from Pipecat docs / spike writeup)
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    const response = await fetch(`/voice/${agent}/offer`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({sdp: pc.localDescription.sdp}),
    });
    const {answer} = await response.json();
    await pc.setRemoteDescription({type: "answer", sdp: answer});
    setState(STATES.LISTENING);
    // Subscribe to data channel events for state transitions
}

connect().catch(err => {
    console.error("voice connection failed", err);
});
```

- [ ] **Step 5: Tests where possible**

Template-render tests: confirm voice.html renders for each supported agent with the right color class.

- [ ] **Step 6: Commit**

```
feat(voice): orb UI as Pipecat client with per-agent color theme

voice.html rewritten — WebRTC client, state machine, twilight-violet
for Aetheria. orb.css uses CSS custom properties so Phase 1.5 can add
Vett (teal) and Scotty (flint grey) by extending the class list.
```

---

## Task 7: Startup wiring + voice service lifecycle

**Files:**
- Modify: `soveryn/app/startup.py`

Build the voice services (Pipecat pipeline factory bound to Aetheria's AgentLoop) and register the voice blueprint. Gate on `ELEVENLABS_API_KEY` being present (no voice if no key).

- [ ] **Step 1: In create_app, after agent_loops are built:**

```python
# Voice — Aetheria only in Phase 1.
from soveryn.platform.voice.config import VoiceConfig
from soveryn.platform.voice.pipeline import build_aetheria_voice_pipeline
from soveryn.platform.voice.providers.elevenlabs import ElevenLabsTTSProvider
from soveryn.app.routes import voice as voice_routes

voice_config = VoiceConfig.from_env(os.environ)
aetheria_character = voice_config.agent_character("aetheria")
voice_state = {}
if aetheria_character is not None:
    tts_provider = ElevenLabsTTSProvider(api_key=voice_config.elevenlabs_api_key)
    voice_state["aetheria"] = {
        "agent_loop": agent_loops["aetheria"],
        "voice_id": aetheria_character.elevenlabs_voice_id,
        "tts_provider": tts_provider,
    }
    app.extensions.setdefault("soveryn", {})["voice"] = voice_state
    app.register_blueprint(voice_routes.bp)
else:
    logger.info(
        "voice disabled — no ELEVENLABS_API_KEY or ELEVENLABS_VOICE_ID_AETHERIA"
    )
```

- [ ] **Step 2: Smoke test bootstrap with voice enabled and disabled**

```python
def test_create_app_skips_voice_when_no_api_key(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    app = create_app()
    assert "/voice" not in [rule.rule for rule in app.url_map.iter_rules()]


def test_create_app_registers_voice_when_api_key_present(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID_AETHERIA", "test-voice-id")
    app = create_app()
    routes = [rule.rule for rule in app.url_map.iter_rules()]
    assert "/voice" in routes
    assert "/voice/<agent>" in routes
```

- [ ] **Step 3: Commit**

```
feat(voice): wire voice services + blueprint into startup, Aetheria-only

Gated on ELEVENLABS_API_KEY presence. No key → blueprint not registered,
no /voice routes appear. Defense in depth: voice feature can be disabled
without code change by clearing the env var.
```

---

## Task 8: Live verification

**Files:** None — manual verification

After all prior tasks land + restart:

- [ ] **Step 1: Restart vnext**

```bash
systemctl --user restart soveryn-vnext.service
```

- [ ] **Step 2: Open `/voice/aetheria` in a browser**

Visit `http://127.0.0.1:5001/voice/aetheria`. Expect: twilight-violet orb visible, state="listening".

- [ ] **Step 3: Have a natural conversation**

Say "morning, what's the salience digest looking like?" Pipecat's VAD detects you're speaking (orb state → "hearing"), Parakeet transcribes (state → "thinking" once your utterance ends), AgentLoop generates response, TTS streams audio back (state → "speaking"), orb is audio-reactive to amplitude.

- [ ] **Step 4: Interrupt mid-sentence**

While she's speaking, start talking. Pipecat's barge-in detection should:
1. Immediately stop TTS playback
2. Cancel the in-flight AgentLoop stream
3. Transition orb to "interrupted" briefly, then "hearing"
4. Process your new utterance

- [ ] **Step 5: Verify conv_store integration**

```bash
sqlite3 ~/soveryn_vnext/data/memory/conversations_vnext.db \
  "SELECT session_id, title, updated_at FROM conversation_meta WHERE title LIKE '[voice]%' ORDER BY updated_at DESC LIMIT 3;"
```

Expect one or more `[voice] aetheria <timestamp>` titled sessions matching your test conversations.

- [ ] **Step 6: Verify Cross-Surface Continuity picks up voice exchange**

Open a fresh UI session (not voice). Ask "what did I say to you in voice just now?" Expect: she retrieves the voice content via her continuity brief, same way Signal exchanges surface.

- [ ] **Step 7: Save shipped-memory note**

`project_soveryn_sovereign_voice_phase1_shipped.md` — commits, latency observations, any rough edges, Phase 1.5 blockers (Vett/Scotty voice choices status), Phase 2 plan-writing trigger.

---

## Self-Review

**Spec coverage (Phase 1 only):**
- ✅ Pipecat foundation — Tasks 4, 7
- ✅ Parakeet STT wired — Task 4
- ✅ ElevenLabs TTS as only Phase 1 provider — Task 3
- ✅ Continuous listening with Silero VAD — Task 4 (via Pipecat)
- ✅ Interruption / barge-in — Task 4 (via Pipecat)
- ✅ Orb UI rewritten as Pipecat WebRTC client — Task 6
- ✅ Sanitization at AgentLoop source (TTS channel) — Task 2 + Task 4
- ✅ `/voice/aetheria` route in vnext, Aetheria-only — Task 5
- ✅ Per-agent route SHAPE (`/voice/<agent>`) in place but only Aetheria wired — Task 5

**Placeholder scan:**
- "Implementation depends on spike findings" (Task 4 Step 3 skeleton) — INTENTIONAL. The spike (prerequisite section) produces concrete code; this plan documents the architectural shape only. Not a placeholder, a deferred specification.
- "exact pattern from Pipecat docs / spike writeup" (Task 6 JS sketch) — same. Spike-driven specifics.
- No "TBD" or "fill in later" anywhere.

**Type consistency:**
- `TTSProvider` ABC → `ElevenLabsTTSProvider` implementation (Tasks 3, 4)
- `VoiceConfig` / `AgentVoiceCharacter` shared across config and startup (Tasks 1, 7)
- `sanitize_for_tts(str) -> str` consistent across sanitize.py and AgentLoop streaming (Tasks 2, 4)

**Execution dependency chain:**
- Tasks 1, 2, 3 are parallel-safe (no inter-task imports)
- Task 4 depends on 2 (sanitize) + 3 (provider) + spike writeup
- Task 5 depends on 4 (pipeline factory exists)
- Task 6 depends on 5 (routes exist)
- Task 7 depends on 4, 5, 6
- Task 8 depends on 7

---

## What unblocks after Phase 1 ships

- **Phase 1.5 plan can be written.** Adds Vett + Scotty routes once their voice characters are sourced. Reuses the same pipeline factory; per-agent voice ID lookup extends `VoiceConfig.agent_character()`.
- **Phase 2 plan can be written.** Evaluation harness for F5-TTS / XTTS-v2 / Sesame; A/B blind tests for each agent. Local TTS providers implement `TTSProvider`; ElevenLabs becomes fallback.
- **Phase 3 plan can be written.** Polish, telemetry, cross-surface verification.

---

## See also

- `docs/superpowers/specs/2026-06-10-sovereign-voice-design.md` — the spec this plan implements
- `docs/superpowers/notes/2026-06-10-pipecat-spike.md` — investigation prerequisite (must exist before Task 4 dispatches)
- [[project-soveryn-path-consolidation-shipped]] — hard prerequisite (data root for voice assets)
- [[project-soveryn-voice-pipeline]] — historical context for the patched-many-times version we're replacing
- [[project-soveryn-cross-surface-continuity-shipped]] — voice sessions auto-flow through the brief (verify in Task 8)
- [[feedback-evaluate-the-shadow-not-the-function]] — judge this build by what it REMOVES (the patch surface) as much as what it adds
- [[feedback-workaround-is-not-architecture]] — applies: the legacy sanitization filter cascade was a workaround that hardened into architecture; this build removes the patch surface by sanitizing at source
