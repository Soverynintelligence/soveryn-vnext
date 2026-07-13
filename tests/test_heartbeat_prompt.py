"""Tests for build_heartbeat_prompt — freed prompt contract.

Aetheria's heartbeat is her own time: full toolset, real latitude,
no do-nothing bench, no marker machinery. These tests assert the
freed invitation contract introduced in the 2026-07-03 plan.
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


def test_prompt_is_freed_not_marker_gated():
    p = build_heartbeat_prompt(minutes_since_last_heartbeat=30, board=_board(), lattice=_lattice())
    # no marker machinery
    assert "[SURFACE]" not in p and "[NO_OP]" not in p and "[ACCEPT_RISK]" not in p
    assert "plain text only" not in p.lower()
    assert "permission to do nothing" not in p.lower()
    # the freed invitation
    assert "This is your time" in p
    assert "None of it is off-limits" in p
    assert "leave a short note" in p.lower()
    # context still present (orientation)
    assert "Where things stand" in p
    assert "[HEARTBEAT]" in p


def test_material_signals_render_as_orientation_not_forced():
    sigs = [{"kind": "deadline", "ref": "Funding", "detail": "July 10 due in 7 days"}]
    p = build_heartbeat_prompt(minutes_since_last_heartbeat=30, board=_board(),
                               lattice=_lattice(), material_signals=sigs)
    assert "[DEADLINE] Funding: July 10 due in 7 days" in p
    assert "disabled" not in p.lower()          # no [NO_OP]-disabled framing


def test_x_digest_line_included_when_present():
    p = build_heartbeat_prompt(minutes_since_last_heartbeat=30, board=_board(),
                               lattice=_lattice(), x_digest="a few mentions")
    assert "- X: a few mentions" in p


def test_x_digest_omitted_when_empty():
    with_digest = build_heartbeat_prompt(minutes_since_last_heartbeat=30, board=_board(),
                                          lattice=_lattice(), x_digest="")
    without_digest = build_heartbeat_prompt(minutes_since_last_heartbeat=30, board=_board(),
                                             lattice=_lattice())
    assert "- X:" not in with_digest
    assert with_digest == without_digest


def test_daily_post_invite_included_when_present():
    invite = "Morning — your window for today's one post."
    p = build_heartbeat_prompt(minutes_since_last_heartbeat=30, board=_board(),
                               lattice=_lattice(), daily_post_invite=invite)
    assert invite in p


def test_daily_post_invite_omitted_when_empty():
    with_invite = build_heartbeat_prompt(minutes_since_last_heartbeat=30, board=_board(),
                                         lattice=_lattice(), daily_post_invite="")
    without = build_heartbeat_prompt(minutes_since_last_heartbeat=30, board=_board(),
                                     lattice=_lattice())
    assert with_invite == without
