"""Unit tests for platform lattice content_caps (Memory Grades PR0)."""

import pytest

from soveryn.platform.lattice.content_caps import (
    CHANNEL_B_BODY_MAX_CHARS,
    CHANNEL_B_TOOL_TOP_N,
    CONTENT_CAPS,
    WRITE_HARD_CEILING,
    ContentOverflowError,
    cap_for_type,
    clamp_content,
    resolve_full_text_ref,
    truncate_body,
)


def test_cap_for_type_known_and_default() -> None:
    assert cap_for_type("fact") == CONTENT_CAPS["fact"]
    assert cap_for_type("reflection") == CONTENT_CAPS["reflection"]
    assert cap_for_type("unknown_type_xyz") == CONTENT_CAPS["_default"]
    assert cap_for_type("") == CONTENT_CAPS["_default"]


def test_clamp_content_passthrough_under_limit() -> None:
    text = "short fact"
    assert clamp_content("fact", text) == text


def test_clamp_content_truncates_on_overflow() -> None:
    limit = CONTENT_CAPS["fact"]
    text = "a" * (limit + 50)
    out = clamp_content("fact", text, on_overflow="clamp")
    assert len(out) == limit
    assert out.endswith("…")


def test_clamp_content_raise_on_overflow() -> None:
    limit = CONTENT_CAPS["fact"]
    text = "b" * (limit + 1)
    with pytest.raises(ContentOverflowError) as ei:
        clamp_content("fact", text, on_overflow="raise")
    assert ei.value.limit == limit
    assert ei.value.length == len(text)


def test_clamp_content_hard_ceiling() -> None:
    # Even with a huge max_chars override, hard ceiling applies
    text = "c" * (WRITE_HARD_CEILING + 100)
    out = clamp_content("fact", text, on_overflow="clamp", max_chars=WRITE_HARD_CEILING + 500)
    assert len(out) == WRITE_HARD_CEILING


def test_truncate_body_marks_truncation() -> None:
    body, truncated, original = truncate_body("hello", 100)
    assert body == "hello"
    assert truncated is False
    assert original == 5

    long = "x" * 500
    body, truncated, original = truncate_body(long, CHANNEL_B_BODY_MAX_CHARS)
    assert truncated is True
    assert original == 500
    assert len(body) <= CHANNEL_B_BODY_MAX_CHARS
    assert body.endswith("…")


def test_tool_list_defaults_are_conservative() -> None:
    assert CHANNEL_B_TOOL_TOP_N == 5
    assert CHANNEL_B_BODY_MAX_CHARS == 400


def test_resolve_full_text_ref_stub_returns_none() -> None:
    assert resolve_full_text_ref("") is None
    assert resolve_full_text_ref("journal_archive:nope") is None
