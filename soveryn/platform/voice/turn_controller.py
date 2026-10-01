"""TurnController — emit interruptions for cascade duplex (PR4a).

Listens for:
  - UPSTREAM BotStartedSpeakingFrame / BotStoppedSpeakingFrame → bot_speaking
  - DOWNSTREAM VADUserStartedSpeakingFrame while bot speaking → maybe barge-in

On accept: ``broadcast_interruption()`` + ``bridge.begin_interrupt()``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from soveryn.platform.voice.duplex_config import DuplexConfig
from soveryn.platform.voice.turn_policy import should_accept_barge

if TYPE_CHECKING:
    from soveryn.platform.voice.pipeline import AgentAdapterBridge

logger = logging.getLogger(__name__)


class TurnController(FrameProcessor):
    """House-owned interruption emitter (Option A in duplex design)."""

    def __init__(
        self,
        *,
        duplex: DuplexConfig,
        bridge: Any | None = None,  # AgentAdapterBridge
    ):
        super().__init__()
        self._duplex = duplex
        self._bridge = bridge
        self.bot_speaking = False
        self._speech_started_at: float | None = None
        self._barge_task: asyncio.Task | None = None
        self._interrupt_pending = False

    def bind_bridge(self, bridge: Any) -> None:
        """Late-bind bridge when constructed before the bridge exists."""
        self._bridge = bridge

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        # Bot playout truth travels UPSTREAM from transport.output (and also
        # downstream). Handle both directions for Bot* frames.
        if isinstance(frame, BotStartedSpeakingFrame):
            self.bot_speaking = True
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, BotStoppedSpeakingFrame):
            self.bot_speaking = False
            self._cancel_barge_wait()
            self._interrupt_pending = False
            await self.push_frame(frame, direction)
            return

        if direction == FrameDirection.DOWNSTREAM:
            if isinstance(frame, VADUserStartedSpeakingFrame):
                await self._on_user_speech_start()
            elif isinstance(frame, VADUserStoppedSpeakingFrame):
                self._cancel_barge_wait()
                self._speech_started_at = None

        await self.push_frame(frame, direction)

    async def _on_user_speech_start(self) -> None:
        self._speech_started_at = time.perf_counter()
        if not self._duplex.barge_in:
            return
        if not self.bot_speaking:
            return
        if self._interrupt_pending:
            return
        self._cancel_barge_wait()
        self._barge_task = asyncio.create_task(self._maybe_barge_after_min())

    async def _maybe_barge_after_min(self) -> None:
        try:
            await asyncio.sleep(self._duplex.min_barge_ms / 1000.0)
        except asyncio.CancelledError:
            return
        if self._speech_started_at is None:
            return
        speech_ms = (time.perf_counter() - self._speech_started_at) * 1000.0
        decision = should_accept_barge(
            barge_in_enabled=self._duplex.barge_in,
            bot_speaking=self.bot_speaking,
            speech_ms=speech_ms,
            min_barge_ms=self._duplex.min_barge_ms,
            interrupt_pending=self._interrupt_pending,
        )
        if not decision.accept:
            logger.debug("barge rejected: %s", decision.reason)
            return
        await self._emit_interrupt()

    async def _emit_interrupt(self) -> None:
        if self._interrupt_pending:
            return
        self._interrupt_pending = True
        logger.info(
            "barge-in accepted bot_speaking=%s min_barge_ms=%s",
            self.bot_speaking,
            self._duplex.min_barge_ms,
        )
        try:
            if self._bridge is not None:
                await self._bridge.begin_interrupt(reason="barge_in")
            await self.broadcast_interruption()
        except Exception:  # noqa: BLE001
            logger.exception("barge-in emit failed")
            self._interrupt_pending = False

    def _cancel_barge_wait(self) -> None:
        if self._barge_task is not None and not self._barge_task.done():
            self._barge_task.cancel()
        self._barge_task = None
