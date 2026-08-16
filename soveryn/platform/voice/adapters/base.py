"""AgentAdapter protocol — text brain behind the duplex voice shell.

See docs/designs/2026-08-16-duplex-voice-shell.md (PR2).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
import asyncio


@dataclass(frozen=True)
class AgentTextChunk:
    """Speakable text fragment for TTS."""

    text: str
    is_final: bool = False


@runtime_checkable
class AgentAdapter(Protocol):
    """Text brain behind the duplex shell. Never sees raw audio."""

    agent_id: str
    voice_id: str  # F5 registry key (agent name) or ElevenLabs UUID
    supports_streaming: bool

    def start_turn(
        self,
        *,
        session_id: str,
        user_text: str,
        cancel_event: asyncio.Event,
        turn_epoch: int,
    ) -> AsyncIterator[AgentTextChunk]:
        """Async iterator of sanitized speakable text for one user turn."""
        ...

    async def on_cancelled(
        self, *, session_id: str, reason: str, turn_epoch: int
    ) -> None:
        """Best-effort cleanup after barge-in / cancel."""
        ...

    async def on_session_end(self, *, session_id: str) -> None:
        """WebRTC disconnect / pipeline teardown."""
        ...


class AgentAdapterBase:
    """Optional base with no-op cancel/session hooks."""

    agent_id: str
    voice_id: str
    supports_streaming: bool = True

    async def on_cancelled(
        self, *, session_id: str, reason: str, turn_epoch: int
    ) -> None:
        return None

    async def on_session_end(self, *, session_id: str) -> None:
        return None
