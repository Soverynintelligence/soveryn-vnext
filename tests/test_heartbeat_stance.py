"""Tests for the three-way stance parser: _parse_stance / _parse_surface_marker.

TDD — written BEFORE implementation.
"""

from __future__ import annotations

import pytest

from soveryn.agents.heartbeat.daemon import _parse_stance, _parse_surface_marker


# ─── _parse_stance: three-way decision ─────────────────────────────────────


def test_surface_marker_returns_surface():
    """[SURFACE] on its own line → decision "SURFACE", marker line stripped."""
    text = "Here is something worth sharing.\n[SURFACE]"
    decision, content = _parse_stance(text)
    assert decision == "SURFACE"
    assert content == "Here is something worth sharing."


def test_accept_risk_marker_returns_accept_risk():
    """[ACCEPT_RISK] on its own line → decision "ACCEPT_RISK", marker stripped."""
    text = "I see the risk, proceeding anyway.\n[ACCEPT_RISK]"
    decision, content = _parse_stance(text)
    assert decision == "ACCEPT_RISK"
    assert content == "I see the risk, proceeding anyway."


def test_no_op_marker_returns_no_op():
    """[NO_OP] on its own line → decision "NO_OP", marker stripped."""
    text = "Nothing to do right now.\n[NO_OP]"
    decision, content = _parse_stance(text)
    assert decision == "NO_OP"
    assert content == "Nothing to do right now."


def test_missing_marker_defaults_to_no_op():
    """No marker present → ("NO_OP", full stripped text)."""
    text = "Just plain content with no marker."
    decision, content = _parse_stance(text)
    assert decision == "NO_OP"
    assert content == "Just plain content with no marker."


def test_last_marker_wins_no_op_then_accept_risk():
    """[NO_OP] appears first, [ACCEPT_RISK] appears last → "ACCEPT_RISK"."""
    text = "[NO_OP]\nSome extra thought.\n[ACCEPT_RISK]"
    decision, content = _parse_stance(text)
    assert decision == "ACCEPT_RISK"
    assert "ACCEPT_RISK" not in content
    assert "NO_OP" not in content


def test_last_marker_wins_accept_risk_then_surface():
    """[ACCEPT_RISK] first, [SURFACE] last → "SURFACE"."""
    text = "First thought.\n[ACCEPT_RISK]\nSecond thought.\n[SURFACE]"
    decision, content = _parse_stance(text)
    assert decision == "SURFACE"
    assert content == "First thought.\nSecond thought."


def test_last_marker_wins_surface_then_no_op():
    """[SURFACE] first, [NO_OP] last → "NO_OP"."""
    text = "Initial content.\n[SURFACE]\nActually, never mind.\n[NO_OP]"
    decision, content = _parse_stance(text)
    assert decision == "NO_OP"
    assert content == "Initial content.\nActually, never mind."


def test_all_three_markers_last_wins():
    """[NO_OP] → [SURFACE] → [ACCEPT_RISK]: last is ACCEPT_RISK."""
    text = "[NO_OP]\nmid\n[SURFACE]\nend\n[ACCEPT_RISK]"
    decision, content = _parse_stance(text)
    assert decision == "ACCEPT_RISK"
    assert content == "mid\nend"


def test_marker_line_is_stripped_from_content():
    """The decision marker line must not appear in the returned content."""
    for marker, expected_decision in [
        ("[SURFACE]", "SURFACE"),
        ("[ACCEPT_RISK]", "ACCEPT_RISK"),
        ("[NO_OP]", "NO_OP"),
    ]:
        text = f"Preceding content.\n{marker}"
        decision, content = _parse_stance(text)
        assert decision == expected_decision
        assert marker not in content


def test_marker_case_insensitive():
    """Markers are case-insensitive."""
    assert _parse_stance("[surface]")[0] == "SURFACE"
    assert _parse_stance("[accept_risk]")[0] == "ACCEPT_RISK"
    assert _parse_stance("[no_op]")[0] == "NO_OP"
    assert _parse_stance("[Surface]")[0] == "SURFACE"
    assert _parse_stance("[Accept_Risk]")[0] == "ACCEPT_RISK"


def test_empty_input_returns_no_op_empty_content():
    """Empty string → ("NO_OP", "")."""
    assert _parse_stance("") == ("NO_OP", "")


def test_whitespace_only_input():
    """Whitespace-only input → ("NO_OP", "")."""
    decision, content = _parse_stance("   \n  \n  ")
    assert decision == "NO_OP"
    assert content == ""


def test_marker_embedded_mid_line_still_detected():
    """Embedded mid-line markers still count for last-wins; the containing
    line is NOT stripped (only full-line markers are stripped)."""
    text = "Mention of [SURFACE] inline.\n[NO_OP]"
    decision, content = _parse_stance(text)
    # [NO_OP] is last so it wins
    assert decision == "NO_OP"
    # The line with inline [SURFACE] is kept because it's not a full-line marker
    assert "Mention of [SURFACE] inline." in content


def test_marker_with_surrounding_whitespace_on_line_is_stripped():
    """A line like '  [SURFACE]  ' (only whitespace + marker) is stripped."""
    text = "Content here.\n  [SURFACE]  \nMore content."
    decision, content = _parse_stance(text)
    assert decision == "SURFACE"
    assert "[SURFACE]" not in content


# ─── _parse_surface_marker: backward-compat wrapper ─────────────────────────


def test_parse_surface_marker_surface_returns_true():
    """_parse_surface_marker wraps _parse_stance: [SURFACE] → (True, content)."""
    surface, content = _parse_surface_marker("Hello.\n[SURFACE]")
    assert surface is True
    assert content == "Hello."


def test_parse_surface_marker_no_op_returns_false():
    """[NO_OP] → (False, content)."""
    surface, content = _parse_surface_marker("Nothing.\n[NO_OP]")
    assert surface is False
    assert content == "Nothing."


def test_parse_surface_marker_accept_risk_returns_false():
    """[ACCEPT_RISK] should NOT surface to primary thread → (False, content)."""
    surface, content = _parse_surface_marker("Risky.\n[ACCEPT_RISK]")
    assert surface is False
    assert content == "Risky."


def test_parse_surface_marker_no_marker_returns_false():
    """No marker → (False, full text stripped)."""
    surface, content = _parse_surface_marker("Plain content.")
    assert surface is False
    assert content == "Plain content."


def test_parse_surface_marker_empty_returns_false_empty():
    """Empty → (False, "")."""
    assert _parse_surface_marker("") == (False, "")
