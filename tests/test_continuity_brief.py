"""Tests for soveryn.platform.continuity.brief.

Pure-function renderer: SessionTail tuples → [CROSS-SURFACE RECENT
ACTIVITY] block. Empty input is the common case and must return "" so
the engine adds zero overhead when nothing happened on other rails.
"""

from __future__ import annotations

from datetime import datetime

from soveryn.platform.continuity import (
    BLOCK_FOOTER,
    BLOCK_HEADER,
    ContinuityConfig,
    PairedTurn,
    SessionTail,
    build_recent_activity_brief,
    estimate_tokens,
)


FIXED_NOW = datetime.fromisoformat("2026-06-09T12:00:00")


def _tail(
    *,
    sid: str = "s1",
    title: str | None = "[signal] aetheria +1",
    updated: str = "2026-06-09T11:30:00",
    pairs: tuple[PairedTurn, ...] = (),
) -> SessionTail:
    return SessionTail(
        session_id=sid,
        title=title,
        updated_at=updated,
        paired_turns=tuple(pairs),
    )


def test_empty_input_returns_empty_string():
    out = build_recent_activity_brief((), config=ContinuityConfig(), now=FIXED_NOW)
    assert out == ""


def test_no_block_header_in_empty_output():
    out = build_recent_activity_brief((), config=ContinuityConfig(), now=FIXED_NOW)
    assert BLOCK_HEADER not in out
    assert BLOCK_FOOTER not in out


def test_single_session_renders_header_and_footer():
    tail = _tail(
        pairs=(PairedTurn(user="hello there", assistant="hi back"),),
    )
    out = build_recent_activity_brief(
        (tail,), config=ContinuityConfig(), now=FIXED_NOW
    )
    assert BLOCK_HEADER in out
    assert BLOCK_FOOTER in out
    assert "hello there" in out
    assert "hi back" in out


def test_session_title_appears_verbatim_in_block():
    tail = _tail(
        title="[signal] aetheria +19102489392",
        pairs=(PairedTurn(user="u", assistant="a"),),
    )
    out = build_recent_activity_brief(
        (tail,), config=ContinuityConfig(), now=FIXED_NOW
    )
    assert "[signal] aetheria +19102489392" in out


def test_multiple_sessions_rendered_in_order():
    newer = _tail(
        sid="newer",
        title="[signal] newer",
        updated="2026-06-09T11:50:00",
        pairs=(PairedTurn(user="new u", assistant="new a"),),
    )
    older = _tail(
        sid="older",
        title="[signal] older",
        updated="2026-06-09T08:00:00",
        pairs=(PairedTurn(user="old u", assistant="old a"),),
    )
    out = build_recent_activity_brief(
        (newer, older), config=ContinuityConfig(), now=FIXED_NOW
    )
    assert out.index("[signal] newer") < out.index("[signal] older")


def test_in_flight_user_turn_renders_assistant_as_in_flight():
    tail = _tail(
        pairs=(PairedTurn(user="any reply?", assistant=None),),
    )
    out = build_recent_activity_brief(
        (tail,), config=ContinuityConfig(), now=FIXED_NOW
    )
    assert "(in flight)" in out
    assert "any reply?" in out


def test_per_session_cap_truncates_oversized_session():
    huge = "x" * 1000
    pairs = tuple(
        PairedTurn(user=f"u{i}-{huge}", assistant=f"a{i}-{huge}") for i in range(6)
    )
    tail = _tail(pairs=pairs)
    cfg = ContinuityConfig(per_session_cap=120, token_budget=10_000)
    out = build_recent_activity_brief((tail,), config=cfg, now=FIXED_NOW)
    # Oversized pairs get dropped from the front; the newest pair must
    # remain (last user marker "u5-" survives), but at least one of the
    # oldest ("u0-") must be gone.
    assert "u5-" in out
    assert "u0-" not in out


def test_total_token_budget_drops_oldest_sessions_first():
    sessions = []
    for i in range(5):
        sessions.append(
            _tail(
                sid=f"s{i}",
                title=f"[signal] s{i}",
                updated=f"2026-06-09T11:{50 - i:02d}:00",
                pairs=(PairedTurn(user=f"u{i}", assistant=f"a{i}"),),
            )
        )
    # Tight budget: header + preamble + footer + ~1 session is all we afford.
    cfg = ContinuityConfig(token_budget=60)
    out = build_recent_activity_brief(
        tuple(sessions), config=cfg, now=FIXED_NOW
    )
    # Newest session (s0) must be in; oldest (s4) must be out.
    assert "[signal] s0" in out
    assert "[signal] s4" not in out


def test_content_head_truncation_uses_ellipsis():
    long_user = "z" * 500
    tail = _tail(pairs=(PairedTurn(user=long_user, assistant="ok"),))
    out = build_recent_activity_brief(
        (tail,), config=ContinuityConfig(), now=FIXED_NOW
    )
    assert "…" in out


def test_relative_time_formatting():
    tail = _tail(
        updated="2026-06-09T11:30:00",
        pairs=(PairedTurn(user="u", assistant="a"),),
    )
    out = build_recent_activity_brief(
        (tail,), config=ContinuityConfig(), now=FIXED_NOW
    )
    assert "30m ago" in out


def test_relative_time_just_now():
    tail = _tail(
        updated="2026-06-09T11:59:30",
        pairs=(PairedTurn(user="u", assistant="a"),),
    )
    out = build_recent_activity_brief(
        (tail,), config=ContinuityConfig(), now=FIXED_NOW
    )
    assert "just now" in out


def test_relative_time_hours_with_minutes():
    tail = _tail(
        updated="2026-06-09T09:43:00",
        pairs=(PairedTurn(user="u", assistant="a"),),
    )
    out = build_recent_activity_brief(
        (tail,), config=ContinuityConfig(), now=FIXED_NOW
    )
    assert "2h17m ago" in out


def test_relative_time_exact_hours():
    tail = _tail(
        updated="2026-06-09T09:00:00",
        pairs=(PairedTurn(user="u", assistant="a"),),
    )
    out = build_recent_activity_brief(
        (tail,), config=ContinuityConfig(), now=FIXED_NOW
    )
    assert "3h ago" in out
    assert "3h0m ago" not in out


def test_untitled_session_renders_as_placeholder():
    tail = _tail(
        title=None,
        pairs=(PairedTurn(user="u", assistant="a"),),
    )
    out = build_recent_activity_brief(
        (tail,), config=ContinuityConfig(), now=FIXED_NOW
    )
    assert "(untitled session)" in out


def test_estimate_tokens_is_char_div_4():
    # Conservative ceil(len/4): empty=0, 1=1, 4=1, 5=2, 8=2, 9=3.
    assert estimate_tokens("") == 0
    assert estimate_tokens("a") == 1
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2
    assert estimate_tokens("a" * 100) == 25
