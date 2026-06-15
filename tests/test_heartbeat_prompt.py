"""Tests for build_heartbeat_prompt's salience_section splice.

The splice must be byte-identical to pre-engine output when the section
is empty — same exact string. Section, when non-empty, lands BEFORE the
close line so reflection is the last thing she reads before the close.

2026-06-15 update: the close line now also carries the [SURFACE]/[NO_OP]
marker requirement per the Coordination Blackout arc close. Tests now
check that the close line CONTAINS "This is your pulse." (still the
reflective anchor) rather than that the whole prompt ENDS WITH it (the
marker phrasing lives on the same final line).
"""

from __future__ import annotations

from soveryn.agents.heartbeat.prompt import (
    BoardSnapshot,
    LatticeSnapshot,
    build_heartbeat_prompt,
)


def _board() -> BoardSnapshot:
    return BoardSnapshot(
        open_signal_count=0,
        open_blueprint_count=0,
        ready_blueprint_count=0,
        open_friction_count=0,
        stalled_blueprint_count=0,
        blocked_blueprint_count=0,
        oldest_open_signal_age_minutes=None,
        oldest_open_blueprint_title=None,
        oldest_open_blueprint_age_hours=None,
    )


def _lattice() -> LatticeSnapshot:
    return LatticeSnapshot(
        new_node_count_recent_window=0,
        recent_window_minutes=60,
        new_contradiction_flag_count=0,
    )


def test_build_heartbeat_prompt_splices_salience_before_close():
    sal = (
        "2 moments resonated since the last heartbeat. "
        "Do any feel like a permanent shift?\n"
        "\n"
        "- [c1] user: \"locked\"\n"
        "  Marker: \"locked\"\n"
    )
    out = build_heartbeat_prompt(
        minutes_since_last_heartbeat=30,
        board=_board(),
        lattice=_lattice(),
        salience_section=sal,
    )
    # Section content present.
    assert "Do any feel like a permanent shift?" in out
    assert "[c1] user:" in out
    # Salience appears BEFORE the close line.
    assert out.index("This is your pulse.") > out.index("Do any feel like a permanent shift?")
    # Reflective anchor + marker requirement both on the closing line.
    assert "This is your pulse." in out
    assert "[SURFACE]" in out
    assert "[NO_OP]" in out


def test_build_heartbeat_prompt_no_salience_section_unchanged():
    """Empty salience_section must produce byte-identical output to
    omitting the kwarg entirely. No leading/trailing whitespace drift,
    no extra blank lines — pre-engine baseline preserved exactly."""
    out_default = build_heartbeat_prompt(
        minutes_since_last_heartbeat=30,
        board=_board(),
        lattice=_lattice(),
    )
    out_empty = build_heartbeat_prompt(
        minutes_since_last_heartbeat=30,
        board=_board(),
        lattice=_lattice(),
        salience_section="",
    )
    assert out_default == out_empty


def test_build_heartbeat_prompt_default_kwarg_is_empty_string():
    """Calling without salience_section is fine — default is ""."""
    out = build_heartbeat_prompt(
        minutes_since_last_heartbeat=None,
        board=_board(),
        lattice=_lattice(),
    )
    assert "[HEARTBEAT]" in out
    assert "This is your pulse." in out
    assert "[SURFACE]" in out
    assert "[NO_OP]" in out
