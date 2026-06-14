"""Temporal context injection — anchor agent's "now" against wall-clock time.

Without this injection, agents confabulate time-of-day from session pacing
(long thread → "it's late"). The context message gives the model an explicit
ISO timestamp + day-of-week + part-of-day label per turn, so it has ground
truth instead of vibe.

Two layers tested here:
 1. _build_temporal_context() — pure-function around the injected `now`,
    covers the four part-of-day buckets and the message format.
 2. process_message integration — the temporal context is SPLICED onto the
    current user message (not added to the prelude), so the prelude stays
    byte-identical across turns and the KV-cache prefix remains reusable.
    The DB row for the user turn stays text-only — same pattern as the
    vision splice.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from soveryn.agents.loop import AgentLoop
from soveryn.inference.llama_server_client import ChatResponse
from soveryn.memory.conversation_store import ConversationStore


# Capturing chat double identical to test_agent_loop._CapturingChat —
# duplicated locally so this file stays self-contained.
class _CapturingChat:
    def __init__(self, *, content="OK", finish_reason="stop"):
        self.calls: list[dict] = []
        self.content = content
        self.finish_reason = finish_reason

    def __call__(self, request, server, timeout=60.0):
        self.calls.append({"request": request, "server": server, "timeout": timeout})
        return ChatResponse(
            content=self.content,
            finish_reason=self.finish_reason,
            tool_calls=None,
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            raw={"choices": [{"message": {"content": self.content}}]},
        )


@pytest.fixture
def conv_store(tmp_path):
    return ConversationStore(tmp_path / "conv.db")


# Minimal test double — _build_temporal_context only reads self/now and
# doesn't touch any other AgentLoop state. We can call it on a bare instance
# created via __new__ without going through the full constructor.
def _bare_loop() -> AgentLoop:
    return AgentLoop.__new__(AgentLoop)


def test_temporal_context_morning():
    """Hours 5:00 through 11:59 are labeled 'morning'."""
    loop = _bare_loop()
    now = datetime(2026, 6, 13, 8, 30, 0, tzinfo=timezone.utc)
    out = loop._build_temporal_context(now=now)
    assert "morning" in out
    assert "afternoon" not in out
    assert "evening" not in out
    assert "night" not in out


def test_temporal_context_afternoon():
    """Hours 12:00 through 16:59 are labeled 'afternoon'."""
    loop = _bare_loop()
    now = datetime(2026, 6, 13, 15, 32, 0, tzinfo=timezone.utc)
    out = loop._build_temporal_context(now=now)
    assert "afternoon" in out
    assert "morning" not in out


def test_temporal_context_evening():
    """Hours 17:00 through 20:59 are labeled 'evening'."""
    loop = _bare_loop()
    now = datetime(2026, 6, 13, 19, 0, 0, tzinfo=timezone.utc)
    out = loop._build_temporal_context(now=now)
    assert "evening" in out


def test_temporal_context_night():
    """Hours 21:00 through 04:59 are labeled 'night'."""
    loop = _bare_loop()
    late_night = datetime(2026, 6, 13, 23, 0, 0, tzinfo=timezone.utc)
    early_morning_still_night = datetime(2026, 6, 14, 3, 30, 0, tzinfo=timezone.utc)
    assert "night" in loop._build_temporal_context(now=late_night)
    assert "night" in loop._build_temporal_context(now=early_morning_still_night)


def test_temporal_context_includes_iso_timestamp():
    """The ISO timestamp is present and machine-parseable."""
    loop = _bare_loop()
    now = datetime(2026, 6, 13, 15, 32, 0, tzinfo=timezone.utc)
    out = loop._build_temporal_context(now=now)
    # ISO format with seconds precision
    assert "2026-06-13T15:32:00" in out


def test_temporal_context_includes_day_of_week():
    """The day name is present so the model can ground 'tomorrow' / 'last week'."""
    loop = _bare_loop()
    # 2026-06-13 is a Saturday
    now = datetime(2026, 6, 13, 15, 32, 0, tzinfo=timezone.utc)
    out = loop._build_temporal_context(now=now)
    assert "Saturday" in out


def test_temporal_context_is_ambient_not_instructional():
    """The shape must be bare data — no directive language telling the model
    what to do with the time. Earlier version carried 'Time of day matters —
    anchor your sense of now against this' which provoked compliance
    behavior: Aetheria narrated the clock in every reply ('anchored.
    Saturday night, 22:49'). The fix is to surface the data and stay
    silent about what to do with it."""
    loop = _bare_loop()
    now = datetime(2026, 6, 13, 15, 32, 0, tzinfo=timezone.utc)
    out = loop._build_temporal_context(now=now)
    # Directive words from the prior version MUST NOT reappear
    forbidden = ("matters", "anchor", "pacing", "vibe", "implied tone")
    for word in forbidden:
        assert word not in out.lower(), (
            f"temporal context regressed to directive language ({word!r}); "
            f"got: {out!r}"
        )


def test_temporal_context_defaults_to_current_time():
    """When called with no argument, uses datetime.now() under the hood."""
    loop = _bare_loop()
    out = loop._build_temporal_context()
    # Must produce a non-empty bracketed temporal context
    assert out.startswith("[Now:")
    assert out.endswith("]")
    # Must contain the current year for sanity
    today_year = str(datetime.now().year)
    assert today_year in out


def test_temporal_context_boundary_05_00_is_morning():
    """Boundary check: 05:00 sharp is morning, 04:59 is still night."""
    loop = _bare_loop()
    out_05_00 = loop._build_temporal_context(
        now=datetime(2026, 6, 13, 5, 0, 0, tzinfo=timezone.utc)
    )
    out_04_59 = loop._build_temporal_context(
        now=datetime(2026, 6, 13, 4, 59, 0, tzinfo=timezone.utc)
    )
    assert "morning" in out_05_00
    assert "night" in out_04_59


def test_temporal_context_boundary_12_00_is_afternoon():
    """Boundary check: 12:00 sharp is afternoon, 11:59 is still morning."""
    loop = _bare_loop()
    out_12_00 = loop._build_temporal_context(
        now=datetime(2026, 6, 13, 12, 0, 0, tzinfo=timezone.utc)
    )
    out_11_59 = loop._build_temporal_context(
        now=datetime(2026, 6, 13, 11, 59, 0, tzinfo=timezone.utc)
    )
    assert "afternoon" in out_12_00
    assert "morning" in out_11_59


# ─── Integration: splice lands on user turn, not the prelude ─────────────────

def test_temporal_context_spliced_into_current_user_message(conv_store):
    """The temporal prefix lands on the LAST (current) user message — not in
    the prelude — so the prelude stays byte-identical across turns and the
    KV-cache prefix remains reusable."""
    capturing = _CapturingChat()
    loop = AgentLoop("aetheria", conv_store, chat_fn=capturing)
    sid = conv_store.new_session("aetheria")
    loop.process_message(sid, "hi")
    request = capturing.calls[0]["request"]

    # No system message in the prelude carries a temporal marker
    system_msgs = [m for m in request.messages if m.role == "system"]
    for m in system_msgs:
        assert not (isinstance(m.content, str) and m.content.startswith("[Now:")), (
            f"temporal context leaked into the prelude as a system message: {m.content!r}"
        )

    # The current (last) user message carries the temporal prefix + the actual user text
    last = request.messages[-1]
    assert last.role == "user"
    assert isinstance(last.content, str)
    assert last.content.startswith("[Now:")
    assert last.content.endswith("\n\nhi")


def test_temporal_context_does_not_pollute_db(conv_store):
    """DB row for the user turn must be text-only — the temporal prefix is
    in-flight only, same pattern as the vision splice."""
    capturing = _CapturingChat()
    loop = AgentLoop("aetheria", conv_store, chat_fn=capturing)
    sid = conv_store.new_session("aetheria")
    loop.process_message(sid, "hello")
    history = conv_store.load_history(sid)
    user_turns = [t for t in history if t.role == "user"]
    assert len(user_turns) == 1
    assert user_turns[0].content == "hello", (
        f"DB row should be the raw user text, not the spliced wire form. "
        f"Got: {user_turns[0].content!r}"
    )


def test_temporal_context_present_on_every_turn(conv_store):
    """The splice runs per-turn (no caching), so turn N also gets a fresh
    temporal prefix on its own user message."""
    capturing = _CapturingChat()
    loop = AgentLoop("aetheria", conv_store, chat_fn=capturing)
    sid = conv_store.new_session("aetheria")
    loop.process_message(sid, "first")
    loop.process_message(sid, "second")

    second_request = capturing.calls[1]["request"]
    last = second_request.messages[-1]
    assert last.role == "user"
    assert isinstance(last.content, str)
    assert last.content.startswith("[Now:")
    assert last.content.endswith("\n\nsecond")

    # Prior user turn (now in history) must NOT carry the temporal prefix —
    # the DB row is clean, so the rebuild reads "first", not the spliced form.
    user_turns_in_history = [m for m in second_request.messages[:-1] if m.role == "user"]
    assert len(user_turns_in_history) == 1
    assert user_turns_in_history[0].content == "first"


def test_temporal_context_preserves_prelude_byte_identity_across_turns(conv_store):
    """Critical regression guard for Codex's SessionContextCache work:
    the system prelude must be byte-identical across consecutive turns so
    the KV-cache prefix stays reusable. If temporal context ever drifts back
    into the prelude, this test catches it."""
    capturing = _CapturingChat()
    loop = AgentLoop(
        "aetheria", conv_store,
        chat_fn=capturing,
        soul_text="stable soul",
        pinned_text="stable pinned",
    )
    sid = conv_store.new_session("aetheria")
    loop.process_message(sid, "first")
    loop.process_message(sid, "second")

    first_system = [m.content for m in capturing.calls[0]["request"].messages if m.role == "system"]
    second_system = [m.content for m in capturing.calls[1]["request"].messages if m.role == "system"]
    assert first_system == second_system, (
        "prelude system messages drifted between turns — temporal context "
        "must NOT be added at the prelude level"
    )
