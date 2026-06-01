"""Tests for soveryn.platform.text — the shared think-markup strip."""

from soveryn.platform.text import strip_think_markup


def test_empty_input_returns_empty():
    assert strip_think_markup("") == ""


def test_clean_text_passes_through_unchanged():
    assert strip_think_markup("hello world") == "hello world"


def test_paired_block_is_stripped_with_text_around_it():
    assert strip_think_markup("intro <think>scratch</think> response") == "intro  response"


def test_paired_block_multiline_is_stripped():
    text = "intro\n<think>\nline 1\nline 2\n</think>\nresponse"
    out = strip_think_markup(text)
    assert "scratch" not in out
    assert "<think>" not in out
    assert "</think>" not in out
    assert "intro" in out
    assert "response" in out


def test_open_tag_without_close_strips_from_open_to_end():
    # Cap saturation or stream cut mid-think — open with no close.
    assert strip_think_markup("speech <think>incomplete reasoning") == "speech "


def test_naked_reasoning_before_lone_close_strips_everything_before():
    # Model emitted reasoning prose with NO opening <think>, then </think>,
    # then the response. The full reasoning prose must be stripped — not
    # just the closing tag itself.
    text = "this is reasoning prose\nmore reasoning.\n</think>\nThe answer."
    out = strip_think_markup(text)
    assert out.strip() == "The answer."
    assert "reasoning" not in out


def test_lone_close_tag_at_start_strips_just_the_tag():
    # Edge of the naked pattern — content immediately starts with </think>.
    assert strip_think_markup("</think>response") == "response"


def test_any_lone_close_strips_everything_before_it_documented_aggression():
    # The naked-RE is intentionally aggressive: any </think> in content with
    # no preceding <think> triggers a strip from start-of-content up to and
    # including the close tag. This matches the bleed shape we observed
    # (model emits reasoning prose with no opening tag, then closes it) at
    # the cost of over-stripping if a response legitimately contains the
    # literal text "</think>" as content. The trade-off is conscious:
    # missing-bleed is worse than rare-overstrip on a tag literal that
    # never appears in normal conversational output.
    text = "real response\nand more </think> tail"
    out = strip_think_markup(text)
    assert "</think>" not in out
    # "real response" got stripped — the naked-RE consumed it as the
    # reasoning prefix to the close tag. Only what's after </think> survives.
    assert "real response" not in out
    assert "tail" in out


def test_case_insensitive():
    assert strip_think_markup("<THINK>scratch</THINK>final") == "final"
    assert strip_think_markup("<Think>x</Think>y") == "y"


def test_naked_pattern_does_not_overstrip_when_open_precedes_close():
    # If a real <think>...</think> block precedes other prose, the paired-block
    # pattern catches it and the naked-RE must NOT additionally consume prose
    # that comes after the block.
    text = "intro\n<think>scratch</think>\nresponse"
    out = strip_think_markup(text)
    assert "intro" in out
    assert "response" in out
    assert "scratch" not in out
