"""Tests for soveryn.agents.loop.process_message_stream."""

import sqlite3
from unittest.mock import patch
import pytest

from soveryn.agents.loop import (
    AgentLoop, AgentLoopError, DoneEvent, ErrorEvent, TokenEvent,
)
from soveryn.inference.llama_server_client import (
    LlamaServerError, LlamaServerTimeout, StreamChunk,
)
from soveryn.memory.conversation_store import ConversationStore


@pytest.fixture
def conv_store(tmp_path):
    return ConversationStore(tmp_path / "conv.db")


def _chunks(*specs):
    """Build a list of StreamChunk from short tuples (delta, finish_reason[, usage])."""
    out = []
    for s in specs:
        delta = s[0]
        finish = s[1] if len(s) > 1 else None
        usage = s[2] if len(s) > 2 else None
        out.append(StreamChunk(delta=delta, finish_reason=finish,
                               tool_calls_delta=None, usage=usage, raw={}))
    return out


class _CapturingStream:
    def __init__(self, chunks=None, raise_exc=None, raise_at_index=None):
        self.calls = []
        self.chunks = chunks or []
        self.raise_exc = raise_exc
        self.raise_at_index = raise_at_index  # raise AFTER yielding n chunks

    def __call__(self, request, server, timeout=120.0):
        self.calls.append({"request": request, "server": server, "timeout": timeout})
        if self.raise_exc is not None and self.raise_at_index is None:
            raise self.raise_exc
        def _gen():
            for i, c in enumerate(self.chunks):
                if self.raise_at_index is not None and i == self.raise_at_index:
                    raise self.raise_exc
                yield c
            # If raise_at_index is beyond the last chunk index, raise after exhaustion
            if (self.raise_exc is not None and self.raise_at_index is not None
                    and self.raise_at_index >= len(self.chunks)):
                raise self.raise_exc
        return _gen()


# ─── Session validation (setup errors propagate as exceptions) ───────────────

def test_stream_missing_session_raises_before_save(conv_store):
    stream = _CapturingStream()
    loop = AgentLoop("aetheria", conv_store, stream_fn=stream)
    with pytest.raises(AgentLoopError, match="does not exist"):
        list(loop.process_message_stream("nope", "hi"))
    assert stream.calls == []


def test_stream_session_belongs_to_other_agent_raises_before_save(conv_store):
    sid = conv_store.new_session("vett")
    stream = _CapturingStream()
    loop = AgentLoop("aetheria", conv_store, stream_fn=stream)
    with pytest.raises(AgentLoopError, match="belongs to agent 'vett'"):
        list(loop.process_message_stream(sid, "hi"))
    assert stream.calls == []
    assert conv_store.load_history(sid) == ()


# ─── Setup errors before first chunk → exception (route → JSON 5xx) ──────────

def test_stream_setup_timeout_propagates(conv_store):
    """LlamaServerTimeout raised before any chunk → propagates as exception."""
    sid = conv_store.new_session("aetheria")
    stream = _CapturingStream(raise_exc=LlamaServerTimeout("aetheria_primary", 120.0))
    loop = AgentLoop("aetheria", conv_store, stream_fn=stream)
    with pytest.raises(LlamaServerTimeout):
        list(loop.process_message_stream(sid, "hi"))
    # User turn DID save (precedes the stream call)
    assert len(conv_store.load_history(sid)) == 1


def test_stream_setup_http_error_propagates(conv_store):
    sid = conv_store.new_session("aetheria")
    stream = _CapturingStream(raise_exc=LlamaServerError(500, "boom", "aetheria_primary"))
    loop = AgentLoop("aetheria", conv_store, stream_fn=stream)
    with pytest.raises(LlamaServerError):
        list(loop.process_message_stream(sid, "hi"))


# ─── Mid-stream failures → ErrorEvent, NO assistant save ─────────────────────

def test_stream_mid_stream_timeout_yields_error_event_no_save(conv_store):
    sid = conv_store.new_session("aetheria")
    stream = _CapturingStream(
        chunks=_chunks(("hi", None), (" there", None)),
        raise_exc=LlamaServerTimeout("aetheria_primary", 120.0),
        raise_at_index=2,
    )
    loop = AgentLoop("aetheria", conv_store, stream_fn=stream)
    events = list(loop.process_message_stream(sid, "hello"))
    # Filter by type — the stream now also carries TTSTokenEvent (sanitized
    # voice channel) alongside TokenEvent. Chat consumers ignore TTS events.
    token_deltas = [e.delta for e in events if isinstance(e, TokenEvent)]
    assert token_deltas == ["hi", " there"]
    assert isinstance(events[-1], ErrorEvent)
    assert events[-1].code == "chat_timeout"
    # NO assistant turn saved (mid-stream failure)
    history = conv_store.load_history(sid)
    assert [t.role for t in history] == ["user"]


def test_stream_mid_stream_server_error_yields_error_event_no_save(conv_store):
    sid = conv_store.new_session("aetheria")
    stream = _CapturingStream(
        chunks=_chunks(("partial", None)),
        raise_exc=LlamaServerError(500, "boom", "aetheria_primary"),
        raise_at_index=1,
    )
    loop = AgentLoop("aetheria", conv_store, stream_fn=stream)
    events = list(loop.process_message_stream(sid, "hi"))
    assert isinstance(events[-1], ErrorEvent)
    assert events[-1].code == "chat_server_error"
    assert [t.role for t in conv_store.load_history(sid)] == ["user"]


def test_stream_stops_without_finish_reason_yields_incomplete_error(conv_store):
    """Constraint 5: no explicit finish_reason → ErrorEvent, no save."""
    sid = conv_store.new_session("aetheria")
    stream = _CapturingStream(chunks=_chunks(("hi", None), (" there", None)))
    loop = AgentLoop("aetheria", conv_store, stream_fn=stream)
    events = list(loop.process_message_stream(sid, "hi"))
    assert isinstance(events[-1], ErrorEvent)
    assert events[-1].code == "incomplete_stream"
    assert [t.role for t in conv_store.load_history(sid)] == ["user"]


# ─── Successful completion → DoneEvent + assistant save ──────────────────────

def test_stream_happy_path_saves_assistant_and_emits_done(conv_store):
    sid = conv_store.new_session("aetheria")
    stream = _CapturingStream(chunks=_chunks(
        ("hi", None),
        (" there", None),
        ("", "stop", {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}),
    ))
    loop = AgentLoop("aetheria", conv_store, stream_fn=stream)
    events = list(loop.process_message_stream(sid, "hello"))
    deltas = [e.delta for e in events if isinstance(e, TokenEvent)]
    assert deltas == ["hi", " there"]
    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert done.content == "hi there"
    assert done.finish_reason == "stop"
    assert done.usage["total_tokens"] == 8
    # Assistant turn saved
    history = conv_store.load_history(sid)
    assert [t.role for t in history] == ["user", "assistant"]
    assert history[1].content == "hi there"


def test_stream_empty_content_with_explicit_finish_is_rejected(conv_store):
    """Post-2026-06-01: empty content + no tool_calls is a generation failure,
    not a valid turn. Saving the empty row poisons future-load context
    (the model degenerates when it sees "prior assistant said nothing for
    this prompt" — see soveryn/agents/loop.py guard). We now refuse to save
    and yield ErrorEvent so the caller can surface the failure clearly."""
    sid = conv_store.new_session("aetheria")
    stream = _CapturingStream(chunks=_chunks(("", "length")))
    loop = AgentLoop("aetheria", conv_store, stream_fn=stream)
    events = list(loop.process_message_stream(sid, "hi"))
    last = events[-1]
    assert isinstance(last, ErrorEvent)
    assert last.code == "empty_generation"
    history = conv_store.load_history(sid)
    # Only the user turn should be persisted; the empty assistant is rejected.
    assert [t.role for t in history] == ["user"]


def test_stream_accumulates_tool_calls_silently_surfaces_in_done(conv_store):
    sid = conv_store.new_session("aetheria")
    chunks = [
        StreamChunk(delta="", finish_reason=None,
                    tool_calls_delta=[{"index": 0, "id": "c1", "type": "function",
                                       "function": {"name": "foo", "arguments": ""}}],
                    usage=None, raw={}),
        StreamChunk(delta="", finish_reason=None,
                    tool_calls_delta=[{"index": 0, "function": {"arguments": "{\""}}],
                    usage=None, raw={}),
        StreamChunk(delta="", finish_reason=None,
                    tool_calls_delta=[{"index": 0, "function": {"arguments": "a\":1}"}}],
                    usage=None, raw={}),
        StreamChunk(delta="", finish_reason="tool_calls", tool_calls_delta=None,
                    usage=None, raw={}),
    ]
    stream = _CapturingStream(chunks=chunks)
    loop = AgentLoop("aetheria", conv_store, stream_fn=stream)
    events = list(loop.process_message_stream(sid, "go"))
    # No partial tool_call events emitted (constraint 2)
    assert all(not isinstance(e, TokenEvent) or e.delta != "" for e in events)
    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert done.tool_calls is not None
    assert len(done.tool_calls) == 1
    assert done.tool_calls[0]["id"] == "c1"
    assert done.tool_calls[0]["function"]["name"] == "foo"
    assert done.tool_calls[0]["function"]["arguments"] == "{\"a\":1}"


# ─── Persona / recall still active in streaming ──────────────────────────────

def test_stream_includes_persona_system_message(conv_store):
    sid = conv_store.new_session("aetheria")
    stream = _CapturingStream(chunks=_chunks(("hi", "stop")))
    loop = AgentLoop("aetheria", conv_store, stream_fn=stream)
    list(loop.process_message_stream(sid, "hello"))
    request = stream.calls[0]["request"]
    assert request.messages[0].role == "system"
    assert "Aetheria" in request.messages[0].content


def test_stream_with_recall_includes_recall_system_message(conv_store, tmp_path):
    from soveryn.memory.lattice import LatticeStore
    sid = conv_store.new_session("aetheria")
    lat = LatticeStore(tmp_path / "lat.db")
    lat.write_node("aetheria", "matched fact", intensity=0.5, embedding=(1.0, 0.0))
    stream = _CapturingStream(chunks=_chunks(("ok", "stop")))
    loop = AgentLoop(
        "aetheria", conv_store, stream_fn=stream,
        lattice_store=lat, recall_k=2, recall_threshold=0.5,
        embed_fn=lambda t: (1.0, 0.0),
    )
    list(loop.process_message_stream(sid, "hi"))
    msgs = stream.calls[0]["request"].messages
    assert [m.role for m in msgs[:3]] == ["system", "system", "user"]
    assert "Uncertain context:" in msgs[1].content


# ─── Souls Step 3: soul_text wiring (streaming path) ─────────────────────────

def test_stream_default_soul_text_skips_soul_message(conv_store):
    """Streaming path: default soul_text='' means no soul system message."""
    captured_requests = []

    def stream(req, server, timeout):
        captured_requests.append(req)
        yield TokenEvent(delta="ok")
        yield DoneEvent(content="ok", finish_reason="stop", tool_calls=None, usage=None)

    loop = AgentLoop("aetheria", conv_store, stream_fn=stream)
    sid = conv_store.new_session("aetheria")
    list(loop.process_message_stream(sid, "hi"))
    system_count = sum(1 for m in captured_requests[0].messages if m.role == "system")
    assert system_count == 1


def test_stream_soul_text_added_as_second_system_message(conv_store):
    """Streaming path: soul_text injects a separate system message after persona."""
    captured_requests = []

    def stream(req, server, timeout):
        captured_requests.append(req)
        yield TokenEvent(delta="ok")
        yield DoneEvent(content="ok", finish_reason="stop", tool_calls=None, usage=None)

    loop = AgentLoop(
        "aetheria", conv_store,
        stream_fn=stream,
        soul_text="STREAM_SOUL_TOKEN",
    )
    sid = conv_store.new_session("aetheria")
    list(loop.process_message_stream(sid, "hi"))
    system_msgs = [m for m in captured_requests[0].messages if m.role == "system"]
    assert len(system_msgs) == 2
    assert system_msgs[1].content == "STREAM_SOUL_TOKEN"


def test_stream_persona_and_soul_kept_separate_at_agent_loop_for_vett(conv_store):
    """Streaming path mirrors sync: AgentLoop keeps semantic layers separate;
    transport adapter `prepare_wire_messages` handles wire folding."""
    captured_requests = []

    def stream(req, server, timeout):
        captured_requests.append(req)
        yield TokenEvent(delta="ok")
        yield DoneEvent(content="ok", finish_reason="stop", tool_calls=None, usage=None)

    loop = AgentLoop(
        "vett", conv_store,
        stream_fn=stream,
        soul_text="STREAM_VETT_SOUL",
    )
    sid = conv_store.new_session("vett")
    list(loop.process_message_stream(sid, "hi"))
    system_msgs = [m for m in captured_requests[0].messages if m.role == "system"]
    assert len(system_msgs) == 2, (
        f"AgentLoop stream path should also keep persona + soul as separate "
        f"ChatMessages. Got {len(system_msgs)}."
    )
    assert "STREAM_VETT_SOUL" not in system_msgs[0].content
    assert system_msgs[1].content == "STREAM_VETT_SOUL"


# ─── Pinned memory wiring (streaming path) ───────────────────────────────────

def test_stream_pinned_text_added_between_persona_and_soul(conv_store):
    """Streaming path: same persona -> pinned -> soul ordering."""
    captured_requests = []

    def stream(req, server, timeout):
        captured_requests.append(req)
        yield TokenEvent(delta="ok")
        yield DoneEvent(content="ok", finish_reason="stop", tool_calls=None, usage=None)

    loop = AgentLoop(
        "aetheria", conv_store,
        stream_fn=stream,
        soul_text="STREAM_SOUL",
        pinned_text="STREAM_PINNED",
    )
    sid = conv_store.new_session("aetheria")
    list(loop.process_message_stream(sid, "hi"))
    system_msgs = [m for m in captured_requests[0].messages if m.role == "system"]
    assert len(system_msgs) == 3
    assert system_msgs[1].content == "STREAM_PINNED"
    assert system_msgs[2].content == "STREAM_SOUL"


# ─── SI-T2: attachments kwarg in streaming path ──────────────────────────────

def test_stream_with_attachments_splices_image_url_into_current_user_message(conv_store):
    """Streaming mirror of sync: wire-level user message is list-content;
    DB row stays text-only."""
    sid = conv_store.new_session("aetheria")
    stream = _CapturingStream(chunks=_chunks(("ok", "stop")))
    loop = AgentLoop("aetheria", conv_store, stream_fn=stream)
    img_url = "data:image/jpeg;base64,AAAA"
    list(loop.process_message_stream(sid, "what's this?", attachments=(img_url,)))

    # DB stores text-only
    history = conv_store.load_history(sid)
    assert history[0].role == "user"
    assert history[0].content == "what's this?"

    # Wire-level message list-content with text + image parts. The text part
    # also carries the temporal-context prefix from the splice ordering
    # (temporal first, then vision wraps it), so we match by suffix.
    sent_user = stream.calls[0]["request"].messages[-1]
    assert sent_user.role == "user"
    assert isinstance(sent_user.content, list)
    text_parts = [p for p in sent_user.content if p.get("type") == "text"]
    assert len(text_parts) == 1
    assert text_parts[0]["text"].endswith("what's this?")
    assert {"type": "image_url", "image_url": {"url": img_url}} in sent_user.content


def test_stream_without_attachments_unchanged(conv_store):
    """Regression: attachments=None preserves prior streaming behavior. The
    temporal splice prepends a prefix to the current user message, but the
    user text still ends with it."""
    sid = conv_store.new_session("aetheria")
    stream = _CapturingStream(chunks=_chunks(("ok", "stop")))
    loop = AgentLoop("aetheria", conv_store, stream_fn=stream)
    list(loop.process_message_stream(sid, "plain text"))
    sent_user = stream.calls[0]["request"].messages[-1]
    assert sent_user.role == "user"
    assert isinstance(sent_user.content, str)
    assert sent_user.content.endswith("plain text")


def test_stream_attachments_on_non_aetheria_raises_before_save(conv_store):
    """Vision guard fires BEFORE save_turn in streaming too — no phantom turn."""
    stream = _CapturingStream(chunks=_chunks(("ok", "stop")))
    loop_vett = AgentLoop("vett", conv_store, stream_fn=stream)
    sid = conv_store.new_session("vett")
    with pytest.raises(AgentLoopError, match="attachments only supported"):
        list(loop_vett.process_message_stream(
            sid, "hi", attachments=("data:image/jpeg;base64,AAAA",),
        ))
    # No user turn saved, no stream dispatched
    assert conv_store.load_history(sid) == ()
    assert stream.calls == []


def test_stream_multiple_attachments_all_spliced(conv_store):
    """Streaming: all image URLs become image_url parts in order."""
    sid = conv_store.new_session("aetheria")
    stream = _CapturingStream(chunks=_chunks(("ok", "stop")))
    loop = AgentLoop("aetheria", conv_store, stream_fn=stream)
    urls = (
        "data:image/jpeg;base64,A",
        "data:image/png;base64,B",
        "data:image/webp;base64,C",
    )
    list(loop.process_message_stream(sid, "compare these", attachments=urls))
    sent = stream.calls[0]["request"].messages[-1]
    assert isinstance(sent.content, list)
    img_parts = [p for p in sent.content if p.get("type") == "image_url"]
    assert len(img_parts) == 3
    assert [p["image_url"]["url"] for p in img_parts] == list(urls)
    # Text part also carries the temporal-context prefix
    text_parts = [p for p in sent.content if p.get("type") == "text"]
    assert len(text_parts) == 1
    assert text_parts[0]["text"].endswith("compare these")
