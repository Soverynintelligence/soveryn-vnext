"""Tests for the heartbeat daemon — trigger eligibility, prompt shape,
and daemon tick lifecycle with a mocked vnext HTTP surface.

Spec: docs/superpowers/specs/2026-06-02-heartbeat.md
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, time, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from soveryn.agents.heartbeat import (
    BoardSnapshot,
    HeartbeatConfig,
    LatticeSnapshot,
    SkipReason,
    TickEligibility,
    build_heartbeat_prompt,
    evaluate_tick,
)
from soveryn.agents.heartbeat.daemon import (
    HEARTBEAT_SESSION_TITLE,
    HeartbeatDaemon,
)
from soveryn.platform.lattice.legacy import LatticeStore
from soveryn.memory.conversation_store import ConversationStore


# ─── HeartbeatConfig from env ───────────────────────────────────────────────

def test_config_from_env_defaults():
    c = HeartbeatConfig.from_env(env={})
    assert c.enabled is True
    assert c.dry_run is False
    assert c.interval_seconds == 1800
    assert c.backoff_seconds == 600
    assert c.quiet_hours == ""


def test_config_from_env_explicit_overrides():
    c = HeartbeatConfig.from_env(env={
        "SOVERYN_HEARTBEAT_ENABLED": "false",
        "SOVERYN_HEARTBEAT_DRY_RUN": "true",
        "SOVERYN_HEARTBEAT_INTERVAL_SECONDS": "900",
        "SOVERYN_HEARTBEAT_BACKOFF_SECONDS": "300",
        "SOVERYN_HEARTBEAT_QUIET_HOURS": "23:00-07:00",
    })
    assert c.enabled is False
    assert c.dry_run is True
    assert c.interval_seconds == 900
    assert c.backoff_seconds == 300
    assert c.quiet_hours == "23:00-07:00"


# ─── Trigger eligibility ────────────────────────────────────────────────────

def _config(**kwargs) -> HeartbeatConfig:
    return HeartbeatConfig(
        enabled=kwargs.get("enabled", True),
        dry_run=kwargs.get("dry_run", False),
        interval_seconds=kwargs.get("interval_seconds", 1800),
        backoff_seconds=kwargs.get("backoff_seconds", 600),
        quiet_hours=kwargs.get("quiet_hours", ""),
    )


def test_disabled_config_skips_with_disabled_reason():
    now = datetime(2026, 6, 2, 12, 0)
    e = evaluate_tick(_config(enabled=False),
                      now=now, last_heartbeat_at=None,
                      last_aetheria_activity_at=None)
    assert e == TickEligibility(False, SkipReason.DISABLED)


def test_interval_gate_skips_before_full_interval():
    now = datetime(2026, 6, 2, 12, 0)
    last = now - timedelta(seconds=600)  # only 10 min ago, interval is 30
    e = evaluate_tick(_config(),
                      now=now, last_heartbeat_at=last,
                      last_aetheria_activity_at=None)
    assert e == TickEligibility(False, SkipReason.INTERVAL)


def test_interval_gate_passes_after_full_interval():
    now = datetime(2026, 6, 2, 12, 0)
    last = now - timedelta(seconds=1801)
    e = evaluate_tick(_config(),
                      now=now, last_heartbeat_at=last,
                      last_aetheria_activity_at=None)
    assert e == TickEligibility(True, None)


def test_first_run_with_no_prior_heartbeat_is_eligible():
    """Daemon's first tick after startup — no prior heartbeat, no activity.
    Should be eligible."""
    e = evaluate_tick(_config(),
                      now=datetime.now(),
                      last_heartbeat_at=None,
                      last_aetheria_activity_at=None)
    assert e.eligible is True


def test_recent_activity_backoff_skips_if_activity_within_window():
    now = datetime(2026, 6, 2, 12, 0)
    last_hb = now - timedelta(hours=2)        # interval is satisfied
    last_act = now - timedelta(seconds=300)   # 5 min ago, backoff is 10
    e = evaluate_tick(_config(),
                      now=now, last_heartbeat_at=last_hb,
                      last_aetheria_activity_at=last_act)
    assert e == TickEligibility(False, SkipReason.BACKOFF)


def test_recent_activity_backoff_passes_if_activity_outside_window():
    now = datetime(2026, 6, 2, 12, 0)
    last_hb = now - timedelta(hours=2)
    last_act = now - timedelta(seconds=601)   # just outside 10 min
    e = evaluate_tick(_config(),
                      now=now, last_heartbeat_at=last_hb,
                      last_aetheria_activity_at=last_act)
    assert e.eligible is True


def test_quiet_hours_skip_during_normal_window():
    now = datetime(2026, 6, 2, 3, 0)  # 3 AM
    e = evaluate_tick(_config(quiet_hours="02:00-06:00"),
                      now=now, last_heartbeat_at=None,
                      last_aetheria_activity_at=None)
    assert e == TickEligibility(False, SkipReason.QUIET_HOURS)


def test_quiet_hours_skip_during_wraparound_window():
    """23:00-07:00 wraps midnight; 3 AM should be inside."""
    now = datetime(2026, 6, 2, 3, 0)
    e = evaluate_tick(_config(quiet_hours="23:00-07:00"),
                      now=now, last_heartbeat_at=None,
                      last_aetheria_activity_at=None)
    assert e.eligible is False
    assert e.skip_reason == SkipReason.QUIET_HOURS


def test_quiet_hours_outside_window_passes():
    now = datetime(2026, 6, 2, 12, 0)  # noon
    e = evaluate_tick(_config(quiet_hours="23:00-07:00"),
                      now=now, last_heartbeat_at=None,
                      last_aetheria_activity_at=None)
    assert e.eligible is True


def test_quiet_hours_empty_means_always_on():
    """Default config: quiet_hours='' — never quiet, always potentially active."""
    for hour in (2, 5, 12, 23):
        now = datetime(2026, 6, 2, hour, 0)
        e = evaluate_tick(_config(quiet_hours=""),
                          now=now, last_heartbeat_at=None,
                          last_aetheria_activity_at=None)
        assert e.eligible is True, f"hour={hour} should be eligible with no quiet hours"


def test_gate_order_disabled_wins_over_interval():
    """If disabled AND inside the interval window, the report should say
    disabled (the more fundamental skip)."""
    now = datetime(2026, 6, 2, 12, 0)
    last = now - timedelta(seconds=100)  # inside interval too
    e = evaluate_tick(_config(enabled=False),
                      now=now, last_heartbeat_at=last,
                      last_aetheria_activity_at=None)
    assert e.skip_reason == SkipReason.DISABLED


# ─── Prompt construction ────────────────────────────────────────────────────

def _board(**kwargs) -> BoardSnapshot:
    return BoardSnapshot(
        open_signal_count=kwargs.get("open_signal_count", 0),
        open_blueprint_count=kwargs.get("open_blueprint_count", 0),
        ready_blueprint_count=kwargs.get("ready_blueprint_count", 0),
        open_friction_count=kwargs.get("open_friction_count", 0),
        stalled_blueprint_count=kwargs.get("stalled_blueprint_count", 0),
        blocked_blueprint_count=kwargs.get("blocked_blueprint_count", 0),
        oldest_open_signal_age_minutes=kwargs.get("oldest_open_signal_age_minutes"),
    )


def _lattice(**kwargs) -> LatticeSnapshot:
    return LatticeSnapshot(
        new_node_count_recent_window=kwargs.get("new_node_count_recent_window", 0),
        recent_window_minutes=kwargs.get("recent_window_minutes", 60),
        new_contradiction_flag_count=kwargs.get("new_contradiction_flag_count", 0),
    )


def test_prompt_has_heartbeat_header():
    p = build_heartbeat_prompt(
        minutes_since_last_heartbeat=30, board=_board(), lattice=_lattice(),
    )
    assert p.startswith("[HEARTBEAT]")


def test_prompt_handles_first_tick_with_no_prior_heartbeat():
    p = build_heartbeat_prompt(
        minutes_since_last_heartbeat=None, board=_board(), lattice=_lattice(),
    )
    assert "First tick since daemon startup" in p


def test_prompt_includes_quantitative_board_state():
    p = build_heartbeat_prompt(
        minutes_since_last_heartbeat=30,
        board=_board(
            open_signal_count=3,
            open_blueprint_count=2,
            ready_blueprint_count=1,
            stalled_blueprint_count=1,
            blocked_blueprint_count=1,
            open_friction_count=1,
            oldest_open_signal_age_minutes=180,
        ),
        lattice=_lattice(new_node_count_recent_window=12),
    )
    # All the numbers Aetheria can act on are present.
    assert "Signal: 3 open" in p
    assert "oldest: 180 min" in p
    assert "Blueprint: 2 open / 1 Ready" in p
    assert "1 stalled" in p
    assert "1 blocked" in p
    assert "Friction: 1 open" in p
    assert "12 new nodes" in p


def test_prompt_contains_active_auditor_three_options():
    p = build_heartbeat_prompt(
        minutes_since_last_heartbeat=30, board=_board(), lattice=_lattice(),
    )
    # The three invitations Aetheria locked in: audit, sift, silence.
    assert "Audit the boards" in p
    assert "Sift the lattice" in p
    assert "Stay silent" in p


def test_prompt_has_no_scratchpad_or_control_markup():
    """The lock-in rule from old-SOVERYN damage: no <RESOLVE>, <DEFER>,
    [TOOL_CALL:], etc. Plain text only."""
    p = build_heartbeat_prompt(
        minutes_since_last_heartbeat=30,
        board=_board(open_signal_count=1),
        lattice=_lattice(),
    )
    forbidden = [
        "<RESOLVE>", "<DEFER>", "<INTERNAL", "[TOOL_CALL",
        "</RESOLVE>", "</DEFER>",
    ]
    for marker in forbidden:
        assert marker not in p, f"forbidden marker {marker!r} found in prompt"


def test_prompt_introduces_itself_as_heartbeat_not_jon():
    p = build_heartbeat_prompt(
        minutes_since_last_heartbeat=30, board=_board(), lattice=_lattice(),
    )
    assert "heartbeat" in p.lower()
    assert "directive" in p.lower()  # "not a directive" framing present
    # Confirm we never pretend to be the user.
    assert "Jon asks" not in p
    assert "Jon says" not in p


def test_prompt_surfaces_contradictions_when_present():
    p = build_heartbeat_prompt(
        minutes_since_last_heartbeat=30,
        board=_board(),
        lattice=_lattice(new_contradiction_flag_count=2),
    )
    assert "2 new contradiction flags" in p


def test_prompt_omits_contradictions_section_when_zero():
    p = build_heartbeat_prompt(
        minutes_since_last_heartbeat=30, board=_board(), lattice=_lattice(),
    )
    assert "contradiction flag" not in p


# ─── Daemon — DB-backed tick (mocked vnext HTTP) ────────────────────────────

@pytest.fixture
def lattice_db(tmp_path):
    """Fresh lattice DB with the full schema (including heartbeat_log)."""
    db = tmp_path / "lattice.db"
    LatticeStore(db)
    return db


@pytest.fixture
def conv_db(tmp_path):
    db = tmp_path / "conv.db"
    ConversationStore(db)
    return db


@pytest.fixture
def daemon(lattice_db, conv_db):
    return HeartbeatDaemon(
        _config(),
        vnext_base="http://127.0.0.1:5001",
        lattice_db=lattice_db,
        conv_db=conv_db,
    )


def _log_rows(lattice_db: Path) -> list[dict]:
    with sqlite3.connect(str(lattice_db)) as con:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute(
            "SELECT * FROM heartbeat_log ORDER BY triggered_at ASC"
        ).fetchall()]


def test_daemon_skipped_tick_writes_log_row(daemon, lattice_db):
    daemon._do_tick(
        now=datetime(2026, 6, 2, 12, 0),
        eligibility=TickEligibility(False, SkipReason.QUIET_HOURS),
    )
    rows = _log_rows(lattice_db)
    assert len(rows) == 1
    assert rows[0]["eligible"] == 0
    assert rows[0]["skip_reason"] == "quiet_hours"
    assert rows[0]["action_taken"] is None
    assert rows[0]["error"] is None


def test_daemon_dry_run_eligible_tick_logs_without_invoking_chat(
    daemon, lattice_db, conv_db,
):
    """In dry-run mode the daemon should build the prompt but never hit the
    HTTP endpoint. action_taken stays None; response_length captures the
    prompt size as a sanity check."""
    dry_daemon = HeartbeatDaemon(
        _config(dry_run=True),
        vnext_base="http://127.0.0.1:5001",
        lattice_db=lattice_db,
        conv_db=conv_db,
    )
    with patch.object(dry_daemon, "_call_vnext_chat") as mock_chat:
        dry_daemon._do_tick(
            now=datetime(2026, 6, 2, 12, 0),
            eligibility=TickEligibility(True, None),
        )
        mock_chat.assert_not_called()
    rows = _log_rows(lattice_db)
    assert len(rows) == 1
    assert rows[0]["eligible"] == 1
    assert rows[0]["dry_run"] == 1
    assert rows[0]["action_taken"] is None
    assert rows[0]["response_length"] is not None
    assert rows[0]["response_length"] > 100  # prompt isn't empty


def test_daemon_live_eligible_tick_invokes_chat_and_logs_result(
    daemon, lattice_db, conv_db,
):
    """Live tick: daemon calls _call_vnext_chat with the heartbeat session
    and writes a row with action_taken/tool_call_count/response_length filled
    based on the response shape."""
    fake_response = {
        "content": "Nothing right now — boards look clean.",
        "tool_calls": [],
    }
    with patch.object(daemon, "_call_vnext_chat", return_value=fake_response) as mock_chat, \
         patch.object(daemon, "_ensure_heartbeat_session", return_value="sid-abc"):
        daemon._do_tick(
            now=datetime(2026, 6, 2, 12, 0),
            eligibility=TickEligibility(True, None),
        )
        mock_chat.assert_called_once()
        call_args = mock_chat.call_args
        assert call_args[0][0] == "sid-abc"
        assert call_args[0][1].startswith("[HEARTBEAT]")
    rows = _log_rows(lattice_db)
    assert len(rows) == 1
    assert rows[0]["eligible"] == 1
    assert rows[0]["dry_run"] == 0
    assert rows[0]["action_taken"] == 0  # no tool calls
    assert rows[0]["tool_call_count"] == 0
    assert rows[0]["response_length"] == len(fake_response["content"])
    assert rows[0]["error"] is None


def test_daemon_live_tick_with_tool_calls_records_action_taken_true(
    daemon, lattice_db, conv_db,
):
    fake_response = {
        "content": "Posted a Signal about the Q3 funding window.",
        "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "create_coordination_node",
                          "arguments": "{}"}},
        ],
    }
    with patch.object(daemon, "_call_vnext_chat", return_value=fake_response), \
         patch.object(daemon, "_ensure_heartbeat_session", return_value="sid-abc"):
        daemon._do_tick(
            now=datetime(2026, 6, 2, 12, 0),
            eligibility=TickEligibility(True, None),
        )
    rows = _log_rows(lattice_db)
    assert rows[0]["action_taken"] == 1
    assert rows[0]["tool_call_count"] == 1


def test_daemon_live_tick_records_error_on_chat_failure(
    daemon, lattice_db, conv_db,
):
    """If the HTTP call raises, the daemon writes an error row and keeps
    going (caller decides to retry on next interval)."""
    with patch.object(daemon, "_call_vnext_chat",
                       side_effect=RuntimeError("boom")), \
         patch.object(daemon, "_ensure_heartbeat_session", return_value="sid-abc"):
        daemon._do_tick(
            now=datetime(2026, 6, 2, 12, 0),
            eligibility=TickEligibility(True, None),
        )
    rows = _log_rows(lattice_db)
    assert len(rows) == 1
    assert rows[0]["error"] is not None
    assert "RuntimeError" in rows[0]["error"]
    assert "boom" in rows[0]["error"]
    assert rows[0]["action_taken"] is None  # never completed


def test_daemon_latest_aetheria_activity_excludes_heartbeat_session(daemon, conv_db):
    """Backoff against Aetheria's own previous heartbeat session would cause
    infinite skipping. The query must exclude the heartbeat session itself."""
    cs = ConversationStore(conv_db)
    cs.new_session("aetheria", title=HEARTBEAT_SESSION_TITLE)
    # Activity should be None because the only session is the heartbeat session.
    assert daemon._latest_aetheria_activity_at() is None
    # Adding a non-heartbeat session DOES count.
    cs.new_session("aetheria", title="real user chat")
    assert daemon._latest_aetheria_activity_at() is not None


def test_daemon_latest_heartbeat_completed_at_returns_none_for_empty_log(daemon):
    assert daemon._latest_heartbeat_completed_at() is None


def test_daemon_latest_heartbeat_completed_at_returns_most_recent_completed_row(
    daemon, lattice_db,
):
    # Write a few rows manually
    with sqlite3.connect(str(lattice_db)) as con:
        con.execute("INSERT INTO heartbeat_log (id, triggered_at, completed_at, eligible) "
                    "VALUES (?, ?, ?, ?)",
                    ("a", "2026-06-02T10:00:00", "2026-06-02T10:00:01", 1))
        con.execute("INSERT INTO heartbeat_log (id, triggered_at, completed_at, eligible) "
                    "VALUES (?, ?, ?, ?)",
                    ("b", "2026-06-02T11:00:00", "2026-06-02T11:00:02", 1))
    result = daemon._latest_heartbeat_completed_at()
    assert result == datetime(2026, 6, 2, 11, 0, 2)
