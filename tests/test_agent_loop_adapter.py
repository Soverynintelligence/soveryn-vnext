"""AgentLoopAdapter — source=voice and streaming contract (PR2)."""

from __future__ import annotations

import asyncio

from soveryn.agents.loop import TTSTokenEvent
from soveryn.platform.voice.adapters.agent_loop import AgentLoopAdapter


class _FakeLoop:
    def __init__(self):
        self.calls: list[dict] = []

    def process_message_stream(self, session_id, user_message, **kwargs):
        self.calls.append({
            "session_id": session_id,
            "user_message": user_message,
            "kwargs": dict(kwargs),
        })
        yield TTSTokenEvent(text="Hello ")
        yield TTSTokenEvent(text="world.")


def test_adapter_passes_source_voice():
    loop = _FakeLoop()
    adapter = AgentLoopAdapter(loop, agent_id="aetheria", voice_id="aetheria")
    assert adapter.agent_id == "aetheria"
    assert adapter.supports_streaming is True

    async def _run():
        cancel = asyncio.Event()
        chunks = []
        async for c in adapter.start_turn(
            session_id="sess-1",
            user_text="hi",
            cancel_event=cancel,
            turn_epoch=0,
        ):
            chunks.append(c.text)
        return chunks

    texts = asyncio.run(_run())
    assert loop.calls
    assert loop.calls[0]["kwargs"].get("source") == "voice"
    assert loop.calls[0]["session_id"] == "sess-1"
    assert loop.calls[0]["user_message"] == "hi"
    # Sentence flush at period
    assert any("world" in t for t in texts)


def test_adapter_honors_cancel_event():
    class SlowLoop:
        def process_message_stream(self, session_id, user_message, **kwargs):
            yield TTSTokenEvent(text="One. ")
            yield TTSTokenEvent(text="Two. ")

    adapter = AgentLoopAdapter(SlowLoop(), agent_id="aetheria")

    async def _run():
        cancel = asyncio.Event()
        cancel.set()  # already cancelled — producer should stop early
        out = []
        async for c in adapter.start_turn(
            session_id="s",
            user_text="x",
            cancel_event=cancel,
            turn_epoch=1,
        ):
            out.append(c.text)
        return out

    # Cancel set before start — may still get empty or partial; must not hang
    asyncio.run(_run())
