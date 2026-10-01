"""TurnController barge-in emitter (PR4a).

Uses push_frame / broadcast_interruption stubs so we do not need a full
Pipecat TaskManager. Async bodies run via asyncio.run (no pytest-asyncio).
"""

from __future__ import annotations

import asyncio
from typing import Any

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from soveryn.platform.voice.duplex_config import DuplexConfig
from soveryn.platform.voice.turn_controller import TurnController


class _FakeBridge:
    def __init__(self) -> None:
        self.begin_calls: list[str] = []
        self.epochs_bumped = 0
        self.turn_epoch = 0
        self._cancel_event: Any = None

    async def begin_interrupt(self, *, reason: str = "barge_in") -> None:
        self.begin_calls.append(reason)
        self.turn_epoch += 1
        self.epochs_bumped += 1


def _wire_stubs(tc: TurnController) -> list[tuple[str, str]]:
    """Stub push_frame + broadcast_interruption; return event log."""
    events: list[tuple[str, str]] = []

    async def _push(frame, direction=FrameDirection.DOWNSTREAM):
        events.append(("push", type(frame).__name__))

    async def _broadcast():
        events.append(("broadcast", "InterruptionFrame"))

    tc.push_frame = _push  # type: ignore[method-assign]
    tc.broadcast_interruption = _broadcast  # type: ignore[method-assign]
    return events


def test_bot_frames_set_bot_speaking_both_directions():
    async def _run():
        tc = TurnController(duplex=DuplexConfig(barge_in=True), bridge=_FakeBridge())
        _wire_stubs(tc)
        assert tc.bot_speaking is False
        await tc.process_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)
        assert tc.bot_speaking is True
        await tc.process_frame(BotStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        assert tc.bot_speaking is False

    asyncio.run(_run())


def test_barge_disabled_never_emits():
    async def _run():
        bridge = _FakeBridge()
        duplex = DuplexConfig(barge_in=False, min_barge_ms=20)
        tc = TurnController(duplex=duplex, bridge=bridge)
        events = _wire_stubs(tc)
        await tc.process_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)
        await tc.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0.08)
        return bridge.begin_calls, events

    begins, events = asyncio.run(_run())
    assert begins == []
    assert not any(e[0] == "broadcast" for e in events)


def test_barge_accepted_after_min_barge_ms():
    async def _run():
        bridge = _FakeBridge()
        duplex = DuplexConfig(barge_in=True, min_barge_ms=40)
        tc = TurnController(duplex=duplex, bridge=bridge)
        events = _wire_stubs(tc)
        await tc.process_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)
        await tc.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0.12)
        return bridge.begin_calls, events, tc._interrupt_pending

    begins, events, pending = asyncio.run(_run())
    assert begins == ["barge_in"]
    assert ("broadcast", "InterruptionFrame") in events
    assert pending is True


def test_short_speech_cancelled_before_min_does_not_barge():
    async def _run():
        bridge = _FakeBridge()
        duplex = DuplexConfig(barge_in=True, min_barge_ms=200)
        tc = TurnController(duplex=duplex, bridge=bridge)
        events = _wire_stubs(tc)
        await tc.process_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)
        await tc.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0.03)
        await tc.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0.25)
        return bridge.begin_calls, events

    begins, events = asyncio.run(_run())
    assert begins == []
    assert not any(e[0] == "broadcast" for e in events)


def test_no_barge_when_bot_idle():
    async def _run():
        bridge = _FakeBridge()
        duplex = DuplexConfig(barge_in=True, min_barge_ms=20)
        tc = TurnController(duplex=duplex, bridge=bridge)
        events = _wire_stubs(tc)
        # bot_speaking stays false
        await tc.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0.06)
        return bridge.begin_calls, events

    begins, events = asyncio.run(_run())
    assert begins == []
    assert not any(e[0] == "broadcast" for e in events)


def test_second_barge_while_pending_is_idempotent():
    async def _run():
        bridge = _FakeBridge()
        duplex = DuplexConfig(barge_in=True, min_barge_ms=20)
        tc = TurnController(duplex=duplex, bridge=bridge)
        events = _wire_stubs(tc)
        await tc.process_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)
        await tc.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0.06)
        # Second speech start while interrupt still pending
        await tc.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0.06)
        return bridge.begin_calls, [e for e in events if e[0] == "broadcast"]

    begins, broadcasts = asyncio.run(_run())
    assert begins == ["barge_in"]
    assert len(broadcasts) == 1


def test_bind_bridge_late():
    async def _run():
        duplex = DuplexConfig(barge_in=True, min_barge_ms=20)
        tc = TurnController(duplex=duplex, bridge=None)
        bridge = _FakeBridge()
        tc.bind_bridge(bridge)
        _wire_stubs(tc)
        await tc.process_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)
        await tc.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0.06)
        return bridge.begin_calls

    assert asyncio.run(_run()) == ["barge_in"]


def test_begin_interrupt_idempotent_on_bridge():
    """InterruptionFrame path + direct begin_interrupt must not double-bump
    while cancel_event is already set (pipeline bridge contract)."""
    from soveryn.platform.voice.pipeline import AgentAdapterBridge

    class _Adapter:
        agent_id = "test"
        voice_id = "test"
        supports_streaming = True

        async def start_turn(self, **kwargs):
            if False:  # pragma: no cover
                yield None
            return

        async def on_cancelled(self, **kwargs):
            pass

        async def on_session_end(self, **kwargs):
            pass

    async def _run():
        bridge = AgentAdapterBridge(
            adapter=_Adapter(),  # type: ignore[arg-type]
            session_id="s",
            metrics=None,
            stt=None,
        )
        # In-flight turn: cancel_event exists; first interrupt sets it.
        bridge._cancel_event = asyncio.Event()
        await bridge.begin_interrupt(reason="barge_in")
        epoch_after_first = bridge.turn_epoch
        assert bridge._cancel_event.is_set()
        await bridge.begin_interrupt(reason="interruption")
        return epoch_after_first, bridge.turn_epoch

    first, second = asyncio.run(_run())
    assert first == 1
    assert second == 1  # no double-bump
