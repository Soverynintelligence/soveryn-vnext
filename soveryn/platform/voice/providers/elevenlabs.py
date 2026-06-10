"""ElevenLabs TTS provider — REST API call with streaming response.

ElevenLabs supports streaming via ``/v1/text-to-speech/{voice_id}/stream``.
We POST text + model_id + voice_settings, receive a chunked audio stream
back, yield as :class:`TTSChunk` instances."""

from __future__ import annotations

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
        # If a test injects a fake httpx.AsyncClient, use it; otherwise the
        # real one is constructed lazily on first call (keeps the import
        # surface lean — httpx is a heavy dep).
        self._http_client = http_client

    @property
    def name(self) -> str:
        return "elevenlabs"

    async def synthesize(
        self,
        text: str,
        *,
        voice_id: str,
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
            "Accept": "audio/mpeg",
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
            raise TTSError(
                f"ElevenLabs synthesis failed: {type(e).__name__}: {e}"
            ) from e
