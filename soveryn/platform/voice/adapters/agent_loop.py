"""AgentLoop-backed voice adapter (Aetheria / Vett / Scotty)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from soveryn.agents.loop import AgentLoop, TTSTokenEvent
from soveryn.platform.voice.adapters.base import (
    AgentAdapterBase,
    AgentTextChunk,
)
from soveryn.platform.voice.sanitize import sanitize_for_tts

logger = logging.getLogger(__name__)

_SENTINEL = object()


class AgentLoopAdapter(AgentAdapterBase):
    """Wraps AgentLoop.process_message_stream for the duplex shell.

    Always passes ``source="voice"`` so conversation_store tags voice turns.

    ``flush_chars`` controls how soon token stream is emitted to TTS (PR3).
    Lower values + TOKEN aggregation reduce first-audio latency; higher values
    (or sentence mode) favor prosody and fewer F5 calls.
    """

    supports_streaming = True

    def __init__(
        self,
        agent_loop: AgentLoop,
        *,
        agent_id: str,
        voice_id: str | None = None,
        flush_chars: int = 16,
        tts_agg: str = "token",
    ):
        self._agent_loop = agent_loop
        self.agent_id = agent_id
        # F5 keys on agent name; ElevenLabs UUID may be separate via build_tts_service.
        self.voice_id = voice_id or agent_id
        self.flush_chars = max(4, int(flush_chars))
        self.tts_agg = (tts_agg or "token").strip().lower()

    async def start_turn(
        self,
        *,
        session_id: str,
        user_text: str,
        cancel_event: asyncio.Event,
        turn_epoch: int,
    ) -> AsyncIterator[AgentTextChunk]:
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        flush_chars = self.flush_chars
        sentence_only = self.tts_agg == "sentence"

        def _producer() -> None:
            pending = ""

            def _flush() -> None:
                nonlocal pending
                if pending.strip():
                    loop.call_soon_threadsafe(queue.put_nowait, pending)
                pending = ""

            try:
                for event in self._agent_loop.process_message_stream(
                    session_id,
                    user_text,
                    source="voice",
                ):
                    if cancel_event.is_set():
                        break
                    if not isinstance(event, TTSTokenEvent):
                        continue
                    chunk = sanitize_for_tts(
                        event.text, preserve_outer_whitespace=True
                    )
                    if not chunk.strip():
                        continue
                    pending += chunk
                    at_sentence = chunk.rstrip()[-1] in ".!?;:"
                    # TOKEN mode: flush at sentence OR flush_chars (first clause
                    # snappier). SENTENCE mode: only sentence boundaries, with
                    # a large safety flush to avoid unbounded buffers.
                    if at_sentence:
                        _flush()
                    elif not sentence_only and len(pending.strip()) >= flush_chars:
                        _flush()
                    elif sentence_only and len(pending.strip()) >= max(flush_chars, 80):
                        _flush()
            except Exception:  # noqa: BLE001
                logger.exception(
                    "AgentLoopAdapter producer failed agent=%s session=%s",
                    self.agent_id,
                    session_id,
                )
            finally:
                _flush()
                loop.call_soon_threadsafe(queue.put_nowait, _SENTINEL)

        producer = asyncio.create_task(asyncio.to_thread(_producer))
        try:
            while True:
                item = await queue.get()
                if item is _SENTINEL:
                    break
                if cancel_event.is_set():
                    break
                yield AgentTextChunk(text=item)
        finally:
            if not producer.done():
                try:
                    await asyncio.wait_for(asyncio.shield(producer), timeout=0.001)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    pass
