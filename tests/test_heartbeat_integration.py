"""Integration tests — prompt + tick wiring + note-capture + thoughts-log +
delta round-trip.

Covers:
1. non-empty note → delivered via _call_vnext_chat to the durable [heartbeat]
   session and NOT copied into any "primary"/main chat (no session mint).
2. empty note → nothing surfaced; still no "primary" session mint.
3. thoughts-log written every pulse with note/tool_calls/surfaced/snapshot.
4. zero-delta → "Environment static" in prompt.
5. round-trip contract → second pulse reads first's "snapshot" via compute_delta.

Contract: a pulse note lives ONLY in the [heartbeat] aetheria session (the
/chat round-trip persists it there). The daemon no longer surfaces the note to
a separate chat, so the old "surfaced" bookkeeping is always False.

Test strategy: fake _call_vnext_chat like the existing daemon tests
(patch.object).  Deploy sentinel pre-seeded 100h before NOW_DT so stall amnesty
is expired and the stall lane is live for seeding material.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from soveryn.agents.heartbeat.daemon import HeartbeatDaemon
from soveryn.agents.heartbeat.prompt import BoardSnapshot, LatticeSnapshot
from soveryn.agents.heartbeat.materiality import MaterialSignal
from soveryn.agents.heartbeat.trigger import HeartbeatConfig, TickEligibility
from soveryn.platform.lattice.legacy import LatticeStore
from soveryn.memory.conversation_store import ConversationStore

# ── Constants ──────────────────────────────────────────────────────────────────

NOW_DT = datetime(2026, 6, 22, 14, 0, 0)

# ── Shared fixtures ────────────────────────────────────────────────────────────


def _make_lattice_db(tmp_path: Path) -> Path:
    """Minimal lattice DB with heartbeat_log + nodes tables."""
    db = tmp_path / "lattice.db"
    LatticeStore(db)
    return db


def _make_conv_db(tmp_path: Path) -> Path:
    db = tmp_path / "conv.db"
    ConversationStore(db)
    return db


def _make_salience_db(tmp_path: Path) -> Path:
    db = tmp_path / "salience.db"
    from soveryn.platform.salience.store import create_buffer_table
    create_buffer_table(db)
    return db


def _live_config() -> HeartbeatConfig:
    return HeartbeatConfig(
        enabled=True,
        interval_seconds=600,
        backoff_seconds=300,
        quiet_hours="",
        dry_run=False,  # live — so _run_tick path executes
    )


def _make_daemon(tmp_path: Path, *, thoughts_path: Path | None = None) -> HeartbeatDaemon:
    """Build a daemon with isolated DBs.

    deploy_sentinel is pre-seeded 100h before NOW_DT so stall amnesty is
    expired — same pattern as test_heartbeat_deadline.py's final test.
    """
    lattice_db = _make_lattice_db(tmp_path)
    conv_db = _make_conv_db(tmp_path)
    salience_db = _make_salience_db(tmp_path)

    # Pre-seed the deploy sentinel 100h before NOW_DT (post-amnesty).
    sentinel_path = tmp_path / "heartbeat_deploy_started_at"
    sentinel_path.write_text((NOW_DT - timedelta(hours=100)).isoformat())

    d = HeartbeatDaemon(
        _live_config(),
        vnext_base="http://127.0.0.1:5001",
        lattice_db=lattice_db,
        conv_db=conv_db,
        salience_db=salience_db,
        deploy_sentinel=sentinel_path,
        thoughts_log_path=thoughts_path if thoughts_path is not None else tmp_path / "thoughts.jsonl",
    )

    return d


# One canonical material signal for tests that need material present.
_ONE_MATERIAL = [
    MaterialSignal(kind="stall", ref="StalledBlueprint", detail="status=Open for 60h (threshold=48h)")
]

# ── Helper: run one live eligible tick with fakes ─────────────────────────────


def _run_tick_with_fakes(
    daemon: HeartbeatDaemon,
    *,
    model_response: str,
    material_signals: list[MaterialSignal],
) -> None:
    """Run one eligible tick, injecting fake chat response + material signals.

    Patches:
      - _call_vnext_chat → returns {"content": model_response, "tool_calls": []}
      - _ensure_heartbeat_session → returns "sid-heartbeat"
      - _gather_material_signals → returns material_signals
    """
    fake_response = {"content": model_response, "tool_calls": []}
    with (
        patch.object(daemon, "_call_vnext_chat", return_value=fake_response),
        patch.object(daemon, "_ensure_heartbeat_session", return_value="sid-heartbeat"),
        patch.object(daemon, "_gather_material_signals", return_value=material_signals),
    ):
        daemon._do_tick(
            now=NOW_DT,
            eligibility=TickEligibility(True, None),
        )


# ── Test 1: non-empty note → lives only in the [heartbeat] session ────────────


def test_note_pulse_lives_only_in_heartbeat_session(tmp_path):
    """Non-empty note → delivered via _call_vnext_chat to the [heartbeat]
    session, and NO separate "primary" chat is written / minted."""
    tlog_path = tmp_path / "thoughts.jsonl"
    d = _make_daemon(tmp_path, thoughts_path=tlog_path)

    note_text = "I looked into the stalled blueprint and found a blocker."
    fake_response = {"content": note_text, "tool_calls": []}
    with (
        patch.object(d, "_call_vnext_chat", return_value=fake_response) as mock_chat,
        patch.object(d, "_ensure_heartbeat_session", return_value="sid-heartbeat"),
        patch.object(d, "_gather_material_signals", return_value=_ONE_MATERIAL),
        patch.object(d, "_post_json") as mock_post,
    ):
        d._do_tick(now=NOW_DT, eligibility=TickEligibility(True, None))

    # The pulse is delivered to Aetheria via the durable heartbeat session
    # (the /chat round-trip is what persists both the prompt and her note there).
    mock_chat.assert_called_once()
    assert mock_chat.call_args.args[0] == "sid-heartbeat"
    assert isinstance(mock_chat.call_args.args[1], str) and mock_chat.call_args.args[1]
    # ...and nothing mints/writes a separate "primary" chat.
    mock_post.assert_not_called()


def test_note_pulse_thoughts_log_surfaced_false(tmp_path):
    """Non-empty note → recorded in thoughts-log with the note text; surfacing
    is removed so surfaced is always False (note lives in [heartbeat] only)."""
    tlog_path = tmp_path / "thoughts.jsonl"
    d = _make_daemon(tmp_path, thoughts_path=tlog_path)

    _run_tick_with_fakes(
        d,
        model_response="Checked the lattice — nothing alarming.",
        material_signals=[],
    )

    from soveryn.agents.heartbeat.thoughts_log import ThoughtsLog
    rec = ThoughtsLog(tlog_path).last()
    assert rec is not None
    assert rec["surfaced"] is False
    assert rec["note"] == "Checked the lattice — nothing alarming."


# ── Test 2: empty note → nothing surfaced, no "primary" mint ──────────────────


def test_empty_note_pulse_surfaces_nothing(tmp_path):
    """Empty response → nothing surfaced and NO "primary" session minted."""
    tlog_path = tmp_path / "thoughts.jsonl"
    d = _make_daemon(tmp_path, thoughts_path=tlog_path)

    fake_response = {"content": "", "tool_calls": []}
    with (
        patch.object(d, "_call_vnext_chat", return_value=fake_response) as mock_chat,
        patch.object(d, "_ensure_heartbeat_session", return_value="sid-heartbeat"),
        patch.object(d, "_gather_material_signals", return_value=[]),
        patch.object(d, "_post_json") as mock_post,
    ):
        d._do_tick(now=NOW_DT, eligibility=TickEligibility(True, None))

    mock_chat.assert_called_once()
    assert mock_chat.call_args.args[0] == "sid-heartbeat"
    mock_post.assert_not_called()  # no "primary" chat write / mint


def test_empty_note_with_material_surfaces_nothing(tmp_path):
    """Empty response even with material signals → nothing surfaced, no mint."""
    tlog_path = tmp_path / "thoughts.jsonl"
    d = _make_daemon(tmp_path, thoughts_path=tlog_path)

    fake_response = {"content": "", "tool_calls": []}
    with (
        patch.object(d, "_call_vnext_chat", return_value=fake_response),
        patch.object(d, "_ensure_heartbeat_session", return_value="sid-heartbeat"),
        patch.object(d, "_gather_material_signals", return_value=_ONE_MATERIAL),
        patch.object(d, "_post_json") as mock_post,
    ):
        d._do_tick(now=NOW_DT, eligibility=TickEligibility(True, None))

    mock_post.assert_not_called()  # material present but still no "primary" mint


def test_empty_note_thoughts_log_surfaced_false(tmp_path):
    """Empty response → thoughts-log has surfaced=False."""
    tlog_path = tmp_path / "thoughts.jsonl"
    d = _make_daemon(tmp_path, thoughts_path=tlog_path)

    _run_tick_with_fakes(
        d,
        model_response="   \n  ",
        material_signals=[],
    )

    from soveryn.agents.heartbeat.thoughts_log import ThoughtsLog
    rec = ThoughtsLog(tlog_path).last()
    assert rec is not None
    assert rec["surfaced"] is False
    assert rec["note"] == ""


# ── Test 3: thoughts-log record schema ────────────────────────────────────────


def test_thoughts_log_written_every_pulse(tmp_path):
    """thoughts-log is written every pulse regardless of note content."""
    tlog_path = tmp_path / "thoughts.jsonl"
    d = _make_daemon(tmp_path, thoughts_path=tlog_path)

    _run_tick_with_fakes(
        d,
        model_response="",
        material_signals=[],
    )

    from soveryn.agents.heartbeat.thoughts_log import ThoughtsLog
    rec = ThoughtsLog(tlog_path).last()
    assert rec is not None, "ThoughtsLog must be written every pulse"


def test_thoughts_log_record_has_required_keys(tmp_path):
    """thoughts-log record has note/tool_calls/surfaced/snapshot/material_signals/delta/ts/pulse_id."""
    tlog_path = tmp_path / "thoughts.jsonl"
    d = _make_daemon(tmp_path, thoughts_path=tlog_path)

    _run_tick_with_fakes(
        d,
        model_response="Something worth noting.",
        material_signals=_ONE_MATERIAL,
    )

    from soveryn.agents.heartbeat.thoughts_log import ThoughtsLog
    rec = ThoughtsLog(tlog_path).last()
    assert rec is not None
    for key in ("pulse_id", "ts", "snapshot", "material_signals", "delta", "note", "tool_calls", "surfaced"):
        assert key in rec, f"thoughts-log record missing required key: {key!r}"


def test_thoughts_log_record_has_snapshot_key(tmp_path):
    """thoughts-log record must include 'snapshot' key (compute_delta contract)."""
    tlog_path = tmp_path / "thoughts.jsonl"
    d = _make_daemon(tmp_path, thoughts_path=tlog_path)

    _run_tick_with_fakes(
        d,
        model_response="Something important.",
        material_signals=_ONE_MATERIAL,
    )

    from soveryn.agents.heartbeat.thoughts_log import ThoughtsLog
    rec = ThoughtsLog(tlog_path).last()
    assert rec is not None
    assert "snapshot" in rec, (
        "'snapshot' key missing from thoughts-log record — "
        "compute_delta reads prev_record['snapshot'] on the next pulse; "
        "this is a load-bearing contract."
    )


def test_thoughts_log_no_decision_or_violation_fields(tmp_path):
    """New contract: 'decision', 'rationale', 'violation' are NOT in the record."""
    tlog_path = tmp_path / "thoughts.jsonl"
    d = _make_daemon(tmp_path, thoughts_path=tlog_path)

    _run_tick_with_fakes(
        d,
        model_response="Pulled on a thread.",
        material_signals=[],
    )

    from soveryn.agents.heartbeat.thoughts_log import ThoughtsLog
    rec = ThoughtsLog(tlog_path).last()
    assert rec is not None
    assert "decision" not in rec, "Old 'decision' field must be removed from thoughts-log"
    assert "rationale" not in rec, "Old 'rationale' field must be removed from thoughts-log"
    assert "violation" not in rec, "Old 'violation' field must be removed from thoughts-log"


# ── Test 4: prompt still renders with delta=False (signature compat) ──────────


def test_prompt_accepts_zero_delta_without_crashing(tmp_path):
    """Freed prompt: delta is accepted for signature compat but no longer
    short-circuits the output. Passing delta.changed=False should not crash
    and should still produce a freed invitation."""
    from soveryn.agents.heartbeat.prompt import build_heartbeat_prompt

    board = BoardSnapshot(
        open_signal_count=0,
        open_blueprint_count=2,
        ready_blueprint_count=0,
        open_friction_count=0,
        stalled_blueprint_count=0,
        blocked_blueprint_count=0,
        oldest_open_signal_age_minutes=None,
        oldest_open_blueprint_title="Some Blueprint",
        oldest_open_blueprint_age_hours=10,
    )
    lattice = LatticeSnapshot(
        new_node_count_recent_window=0,
        recent_window_minutes=60,
        new_contradiction_flag_count=0,
    )
    prompt = build_heartbeat_prompt(
        minutes_since_last_heartbeat=60,
        board=board,
        lattice=lattice,
        material_signals=[],
        delta={"changed": False, "items": []},
    )
    # Freed contract: orientation context always present, no short-circuit
    assert "[HEARTBEAT]" in prompt
    assert "This is your time" in prompt
    assert "Where things stand" in prompt
    # "Environment static" short-circuit is GONE in the freed prompt
    assert "Environment static" not in prompt


# ── Test 5: snapshot round-trip — second pulse reads first's snapshot ──────────


class TestSnapshotRoundTrip:
    def test_second_pulse_reads_first_snapshot_via_compute_delta(self, tmp_path):
        """Round-trip contract: pulse 1 writes a 'snapshot' key to thoughts-log;
        pulse 2 calls compute_delta(current, thoughts_log.last()) and the
        'snapshot' from pulse 1 is correctly read as prev_snapshot.

        If 'snapshot' is missing from pulse-1's record, compute_delta gets
        prev_snapshot={} and reports changed=True for every board count
        (0 vs actual values). This test catches that regression.
        """
        from soveryn.agents.heartbeat.thoughts_log import ThoughtsLog
        from soveryn.agents.heartbeat.delta import compute_delta

        tlog_path = tmp_path / "thoughts.jsonl"
        d = _make_daemon(tmp_path, thoughts_path=tlog_path)

        # Pulse 1 — model leaves a note, board has 2 open blueprints.
        _run_tick_with_fakes(
            d,
            model_response="Something important.",
            material_signals=[],
        )

        # Read what pulse 1 wrote.
        tlog = ThoughtsLog(tlog_path)
        rec1 = tlog.last()
        assert rec1 is not None, "Pulse 1 must write a thoughts-log record"
        assert "snapshot" in rec1, "Pulse 1 record must have 'snapshot' key"

        # Now simulate pulse 2: build the same snapshot and compute delta.
        # The board should look identical to what pulse 1 saw (same DB state).
        # compute_delta should report changed=False (no board movement, no new signals).
        current_snapshot = rec1["snapshot"]  # Identical to what pulse 1 observed
        delta2 = compute_delta(current_snapshot, rec1)

        # The key assertion: because snapshot was properly stored, compute_delta
        # has full prev data and can tell the environment is unchanged.
        assert delta2["changed"] is False, (
            f"Expected changed=False on round-trip (identical snapshot), "
            f"got items={delta2['items']}. "
            f"This means 'snapshot' was not properly stored in pulse 1's record."
        )

    def test_second_pulse_detects_real_change_from_first_snapshot(self, tmp_path):
        """If the board DID change between pulses, compute_delta must detect it."""
        from soveryn.agents.heartbeat.thoughts_log import ThoughtsLog
        from soveryn.agents.heartbeat.delta import compute_delta

        tlog_path = tmp_path / "thoughts.jsonl"
        d = _make_daemon(tmp_path, thoughts_path=tlog_path)

        # Pulse 1.
        _run_tick_with_fakes(
            d,
            model_response="",
            material_signals=[],
        )

        rec1 = ThoughtsLog(tlog_path).last()
        assert rec1 is not None
        snapshot1 = rec1["snapshot"]

        # Simulate a board change: new signal arrived.
        changed_snapshot = dict(snapshot1)
        changed_board = dict(snapshot1["board"])
        changed_board["open_signal_count"] = snapshot1["board"]["open_signal_count"] + 1
        changed_snapshot = {
            "board": changed_board,
            "material_signals": snapshot1["material_signals"],
            "lattice": snapshot1["lattice"],
        }

        delta2 = compute_delta(changed_snapshot, rec1)
        assert delta2["changed"] is True
        assert any("signal" in item.lower() for item in delta2["items"])


# ── Test 6: prompt material_signals rendering ─────────────────────────────────


class TestPromptMaterialSignalsRendering:
    """Directly test build_heartbeat_prompt with material_signals kwarg."""

    def _board(self) -> BoardSnapshot:
        return BoardSnapshot(
            open_signal_count=0,
            open_blueprint_count=2,
            ready_blueprint_count=0,
            open_friction_count=0,
            stalled_blueprint_count=1,
            blocked_blueprint_count=0,
            oldest_open_signal_age_minutes=None,
            oldest_open_blueprint_title=None,
            oldest_open_blueprint_age_hours=None,
        )

    def _lattice(self) -> LatticeSnapshot:
        return LatticeSnapshot(
            new_node_count_recent_window=0,
            recent_window_minutes=60,
            new_contradiction_flag_count=0,
        )

    def test_material_signals_render_in_prompt(self):
        """When material_signals non-empty, their details appear in the prompt."""
        from soveryn.agents.heartbeat.prompt import build_heartbeat_prompt
        signals = [
            MaterialSignal(kind="stall", ref="MyBlueprint", detail="status=Open for 60h"),
        ]
        prompt = build_heartbeat_prompt(
            minutes_since_last_heartbeat=30,
            board=self._board(),
            lattice=self._lattice(),
            material_signals=signals,
            delta={"changed": True, "items": ["stalled blueprint count changed: 0 → 1"]},
        )
        assert "MyBlueprint" in prompt
        assert "60h" in prompt

    def test_material_signals_render_as_orientation_not_forced(self):
        """Material signals appear as orientation context, not a forced directive."""
        from soveryn.agents.heartbeat.prompt import build_heartbeat_prompt
        signals = [
            MaterialSignal(kind="deadline", ref="NC-Grant", detail="due in 2 days"),
        ]
        prompt = build_heartbeat_prompt(
            minutes_since_last_heartbeat=30,
            board=self._board(),
            lattice=self._lattice(),
            material_signals=signals,
            delta={"changed": True, "items": ["new deadline signal"]},
        )
        # Freed prompt: material signals are visible but NO_OP is not disabled
        assert "NC-Grant" in prompt
        assert "disabled" not in prompt.lower()
        assert "[NO_OP]" not in prompt
