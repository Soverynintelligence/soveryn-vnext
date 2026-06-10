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
    """Raised when TTS synthesis fails.

    Pipeline should fall back to next provider or surface a user-facing error."""


class TTSProvider(ABC):
    """Abstract TTS provider.

    ``synthesize(text)`` is an async generator yielding :class:`TTSChunk`
    instances. Streaming providers (ElevenLabs HTTP/WebSocket) yield as
    audio arrives; non-streaming providers yield a single chunk with
    ``is_final=True``."""

    @abstractmethod
    async def synthesize(self, text: str, *, voice_id: str) -> AsyncIterator[TTSChunk]:
        """Synthesize ``text`` using ``voice_id``. Yield audio chunks."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name for logging/telemetry."""
        ...
