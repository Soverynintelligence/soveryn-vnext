"""Tests for the sanitized TTS text channel on AgentLoop.process_message_stream.

The voice pipeline consumes a parallel ``TTSTokenEvent`` stream emitted
alongside the existing ``TokenEvent`` stream. The chat path's event stream
must remain unchanged — adding TTSTokenEvent is purely additive.

See:
- soveryn/platform/voice/sanitize.py — the sanitization function applied
  per-chunk before TTSTokenEvent is emitted
- docs/superpowers/specs/2026-06-10-sovereign-voice-design.md — the
  "sanitize at source, single boundary" architecture decision
"""

import pytest

from soveryn.agents.loop import (
    AgentLoop, DoneEvent, ErrorEvent, TokenEvent, TTSTokenEvent,
)
from soveryn.inference.llama_server_client import StreamChunk
from soveryn.memory.conversation_store import ConversationStore


@pytest.fixture
def conv_store(tmp_path):
    return ConversationStore(tmp_path / "conv.db")


def _chunks(*specs):
    out = []
    for s in specs:
        delta = s[0]
        finish = s[1] if len(s) > 1 else None
        usage = s[2] if len(s) > 2 else None
        out.append(StreamChunk(delta=delta, finish_reason=finish,
                               tool_calls_delta=None, usage=usage, raw={}))
    return out


class _Stream:
    def __init__(self, chunks):
        self.chunks = chunks

    def __call__(self, request, server, timeout=120.0):
        def _gen():
            for c in self.chunks:
                yield c
        return _gen()


def test_process_message_stream_emits_tts_token_event_alongside_token_event(conv_store):
    sid = conv_store.new_session("aetheria")
    stream = _Stream(_chunks(
        ("hello", None),
        (" world", None),
        ("", "stop"),
    ))
    loop = AgentLoop("aetheria", conv_store, stream_fn=stream)
    events = list(loop.process_message_stream(sid, "hi"))

    # Each non-empty content chunk yields BOTH a TokenEvent and a TTSTokenEvent
    token_events = [e for e in events if isinstance(e, TokenEvent)]
    tts_events = [e for e in events if isinstance(e, TTSTokenEvent)]
    assert [e.delta for e in token_events] == ["hello", " world"]
    # "hello" sanitizes to "hello"; " world" trims to "world"
    assert [e.text for e in tts_events] == ["hello", "world"]

    # Final event is still DoneEvent — TTSTokenEvent doesn't displace it
    assert isinstance(events[-1], DoneEvent)


def test_tts_token_event_is_sanitized(conv_store):
    """A chunk containing <think>...</think> markup must NOT appear in the
    TTSTokenEvent text. The chat path keeps the raw content; TTS gets clean."""
    sid = conv_store.new_session("aetheria")
    stream = _Stream(_chunks(
        ("<think>weighing</think>The answer is forty-two.", None),
        ("", "stop"),
    ))
    loop = AgentLoop("aetheria", conv_store, stream_fn=stream)
    events = list(loop.process_message_stream(sid, "hi"))

    # TokenEvent carries the raw delta (markup included) — chat path unchanged
    token_events = [e for e in events if isinstance(e, TokenEvent)]
    assert token_events[0].delta == "<think>weighing</think>The answer is forty-two."

    # TTSTokenEvent carries the sanitized text
    tts_events = [e for e in events if isinstance(e, TTSTokenEvent)]
    assert len(tts_events) == 1
    assert "<think>" not in tts_events[0].text
    assert "</think>" not in tts_events[0].text
    assert "weighing" not in tts_events[0].text
    assert "The answer is forty-two." in tts_events[0].text


def test_chat_consumers_can_ignore_tts_token_events_without_breaking(conv_store):
    """Chat path subscribers filter for TokenEvent / DoneEvent / ErrorEvent
    only. The presence of TTSTokenEvent in the stream is invisible to them."""
    sid = conv_store.new_session("aetheria")
    stream = _Stream(_chunks(
        ("part one ", None),
        ("part two", None),
        ("", "stop"),
    ))
    loop = AgentLoop("aetheria", conv_store, stream_fn=stream)
    events = list(loop.process_message_stream(sid, "hi"))

    # Simulate chat consumer ignoring TTSTokenEvent
    chat_events = [
        e for e in events
        if not isinstance(e, TTSTokenEvent)
    ]
    deltas = [e.delta for e in chat_events if isinstance(e, TokenEvent)]
    assert deltas == ["part one ", "part two"]

    # Done event is the last non-TTS event
    done = [e for e in chat_events if isinstance(e, DoneEvent)]
    assert len(done) == 1
    assert done[0].content == "part one part two"

    # Conversation persisted with full content (unchanged by TTS channel)
    history = conv_store.load_history(sid)
    assert [t.role for t in history] == ["user", "assistant"]
    assert history[1].content == "part one part two"


def test_tts_token_event_not_emitted_for_empty_sanitized_chunks(conv_store):
    """If a chunk is ALL markup that sanitization strips to nothing, no
    TTSTokenEvent fires for that chunk. The chat path still sees the raw
    TokenEvent (the markup belongs in conv_store and the UI ledger)."""
    sid = conv_store.new_session("aetheria")
    # First chunk is pure scratchpad markup — sanitizes to empty.
    # Second chunk has real prose — TTS sees it.
    stream = _Stream(_chunks(
        ("[SCRATCHPAD: gathering]\n", None),
        ("ready now.", None),
        ("", "stop"),
    ))
    loop = AgentLoop("aetheria", conv_store, stream_fn=stream)
    events = list(loop.process_message_stream(sid, "hi"))

    token_events = [e for e in events if isinstance(e, TokenEvent)]
    tts_events = [e for e in events if isinstance(e, TTSTokenEvent)]

    # BOTH chunks fire TokenEvent (chat sees everything)
    assert len(token_events) == 2

    # Only the prose chunk fires TTSTokenEvent (markup-only chunk dropped)
    assert len(tts_events) == 1
    assert tts_events[0].text == "ready now."


def test_tts_token_event_skipped_for_pure_emoji_chunks(conv_store):
    """Emoji break TTS prosody; a chunk that is purely emoji sanitizes to
    empty whitespace and must not fire TTSTokenEvent."""
    sid = conv_store.new_session("aetheria")
    stream = _Stream(_chunks(
        ("✨", None),
        ("text after", None),
        ("", "stop"),
    ))
    loop = AgentLoop("aetheria", conv_store, stream_fn=stream)
    events = list(loop.process_message_stream(sid, "hi"))

    tts_events = [e for e in events if isinstance(e, TTSTokenEvent)]
    assert [e.text for e in tts_events] == ["text after"]
