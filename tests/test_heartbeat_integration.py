"""Task 7 (original Task 5) Integration tests — prompt + tick wiring +
forced stance + fail-safe + thoughts-log + delta round-trip.

Covers:
1. material + [SURFACE]       → _surface_to_primary_thread called; thoughts-log
                                 decision=SURFACE; record has "snapshot" key.
2. material + [ACCEPT_RISK]   → NOT surfaced; thoughts-log decision=ACCEPT_RISK
                                 with justification.
3. material + [NO_OP]         → fail-safe: warning logged AND material summary
                                 surfaced; thoughts-log notes the violation.
4. non-material + [NO_OP]     → not surfaced (valid silence).
5. zero-delta                 → built prompt contains "Environment static" single-line.
6. round-trip contract        → second pulse reads first's "snapshot" via compute_delta.

Test strategy: fake _call_vnext_chat and _surface_to_primary_thread like the
existing daemon tests (patch.object).  Deploy sentinel pre-seeded 100h before
NOW_DT so stall amnesty is expired and the stall lane is live for seeding material.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, call, patch

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


# ── Test 1: material + [SURFACE] ──────────────────────────────────────────────


class TestMaterialSurface:
    def test_surface_to_primary_thread_called(self, tmp_path):
        """material + [SURFACE] → _surface_to_primary_thread is called."""
        tlog_path = tmp_path / "thoughts.jsonl"
        d = _make_daemon(tmp_path, thoughts_path=tlog_path)

        with patch.object(d, "_surface_to_primary_thread") as mock_surface:
            _run_tick_with_fakes(
                d,
                model_response="The stall is critical.\n[SURFACE]",
                material_signals=_ONE_MATERIAL,
            )
            mock_surface.assert_called_once()

    def test_thoughts_log_decision_is_surface(self, tmp_path):
        """material + [SURFACE] → thoughts-log record decision=SURFACE."""
        tlog_path = tmp_path / "thoughts.jsonl"
        d = _make_daemon(tmp_path, thoughts_path=tlog_path)

        with patch.object(d, "_surface_to_primary_thread"):
            _run_tick_with_fakes(
                d,
                model_response="Stall is blocking progress.\n[SURFACE]",
                material_signals=_ONE_MATERIAL,
            )

        from soveryn.agents.heartbeat.thoughts_log import ThoughtsLog
        rec = ThoughtsLog(tlog_path).last()
        assert rec is not None, "Expected a thoughts-log record to be written"
        assert rec["decision"] == "SURFACE"

    def test_thoughts_log_record_has_snapshot_key(self, tmp_path):
        """thoughts-log record must include 'snapshot' key (compute_delta contract)."""
        tlog_path = tmp_path / "thoughts.jsonl"
        d = _make_daemon(tmp_path, thoughts_path=tlog_path)

        with patch.object(d, "_surface_to_primary_thread"):
            _run_tick_with_fakes(
                d,
                model_response="Something important.\n[SURFACE]",
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


# ── Test 2: material + [ACCEPT_RISK] ─────────────────────────────────────────


class TestMaterialAcceptRisk:
    def test_not_surfaced_on_accept_risk(self, tmp_path):
        """material + [ACCEPT_RISK] → _surface_to_primary_thread NOT called."""
        tlog_path = tmp_path / "thoughts.jsonl"
        d = _make_daemon(tmp_path, thoughts_path=tlog_path)

        with patch.object(d, "_surface_to_primary_thread") as mock_surface:
            _run_tick_with_fakes(
                d,
                model_response="I acknowledge the stall risk.\n[ACCEPT_RISK] Deferring until tomorrow.",
                material_signals=_ONE_MATERIAL,
            )
            mock_surface.assert_not_called()

    def test_thoughts_log_decision_is_accept_risk(self, tmp_path):
        """material + [ACCEPT_RISK] → thoughts-log decision=ACCEPT_RISK."""
        tlog_path = tmp_path / "thoughts.jsonl"
        d = _make_daemon(tmp_path, thoughts_path=tlog_path)

        with patch.object(d, "_surface_to_primary_thread"):
            _run_tick_with_fakes(
                d,
                model_response="Stall acknowledged.\n[ACCEPT_RISK] Will address Monday.",
                material_signals=_ONE_MATERIAL,
            )

        from soveryn.agents.heartbeat.thoughts_log import ThoughtsLog
        rec = ThoughtsLog(tlog_path).last()
        assert rec is not None
        assert rec["decision"] == "ACCEPT_RISK"

    def test_thoughts_log_records_justification(self, tmp_path):
        """material + [ACCEPT_RISK] → rationale in thoughts-log is non-empty."""
        tlog_path = tmp_path / "thoughts.jsonl"
        d = _make_daemon(tmp_path, thoughts_path=tlog_path)

        with patch.object(d, "_surface_to_primary_thread"):
            _run_tick_with_fakes(
                d,
                model_response="Stall acknowledged.\n[ACCEPT_RISK] Will address Monday.",
                material_signals=_ONE_MATERIAL,
            )

        from soveryn.agents.heartbeat.thoughts_log import ThoughtsLog
        rec = ThoughtsLog(tlog_path).last()
        assert rec is not None
        assert rec.get("rationale"), "Rationale should be non-empty for ACCEPT_RISK"


# ── Test 3: material + [NO_OP] → fail-safe ────────────────────────────────────


class TestMaterialNoOpFailSafe:
    def test_warning_logged_on_protocol_violation(self, tmp_path, caplog):
        """material + [NO_OP] → logger.warning about protocol violation."""
        tlog_path = tmp_path / "thoughts.jsonl"
        d = _make_daemon(tmp_path, thoughts_path=tlog_path)

        with (
            patch.object(d, "_surface_to_primary_thread"),
            caplog.at_level(logging.WARNING, logger="soveryn.agents.heartbeat.daemon"),
        ):
            _run_tick_with_fakes(
                d,
                model_response="Nothing to see here.\n[NO_OP]",
                material_signals=_ONE_MATERIAL,
            )

        # A WARNING must have been emitted by the daemon logger.
        warning_msgs = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("violation" in msg.lower() or "protocol" in msg.lower() or "fail-safe" in msg.lower()
                   for msg in warning_msgs), (
            f"Expected a protocol-violation warning, got: {warning_msgs}"
        )

    def test_material_summary_surfaced_as_failsafe(self, tmp_path):
        """material + [NO_OP] → _surface_to_primary_thread IS called (fail-safe)."""
        tlog_path = tmp_path / "thoughts.jsonl"
        d = _make_daemon(tmp_path, thoughts_path=tlog_path)

        with patch.object(d, "_surface_to_primary_thread") as mock_surface:
            _run_tick_with_fakes(
                d,
                model_response="Nothing to surface.\n[NO_OP]",
                material_signals=_ONE_MATERIAL,
            )
            mock_surface.assert_called_once()

    def test_thoughts_log_notes_violation(self, tmp_path):
        """material + [NO_OP] → thoughts-log record notes the violation."""
        tlog_path = tmp_path / "thoughts.jsonl"
        d = _make_daemon(tmp_path, thoughts_path=tlog_path)

        with patch.object(d, "_surface_to_primary_thread"):
            _run_tick_with_fakes(
                d,
                model_response="Silence.\n[NO_OP]",
                material_signals=_ONE_MATERIAL,
            )

        from soveryn.agents.heartbeat.thoughts_log import ThoughtsLog
        rec = ThoughtsLog(tlog_path).last()
        assert rec is not None
        # The record should note the violation somehow — either in decision,
        # rationale, or a dedicated field.
        record_str = json.dumps(rec).lower()
        assert "violation" in record_str or "fail_safe" in record_str or "failsafe" in record_str or "fail-safe" in record_str, (
            f"Expected thoughts-log to record the violation, got: {rec}"
        )


# ── Test 4: non-material + [NO_OP] → valid silence ───────────────────────────


class TestNonMaterialNoOp:
    def test_not_surfaced_when_no_material(self, tmp_path):
        """non-material + [NO_OP] → _surface_to_primary_thread NOT called."""
        tlog_path = tmp_path / "thoughts.jsonl"
        d = _make_daemon(tmp_path, thoughts_path=tlog_path)

        with patch.object(d, "_surface_to_primary_thread") as mock_surface:
            _run_tick_with_fakes(
                d,
                model_response="Board looks stable.\n[NO_OP]",
                material_signals=[],  # no material signals
            )
            mock_surface.assert_not_called()

    def test_thoughts_log_written_even_for_no_op(self, tmp_path):
        """thoughts-log is written every pulse regardless of decision."""
        tlog_path = tmp_path / "thoughts.jsonl"
        d = _make_daemon(tmp_path, thoughts_path=tlog_path)

        with patch.object(d, "_surface_to_primary_thread"):
            _run_tick_with_fakes(
                d,
                model_response="Quiet.\n[NO_OP]",
                material_signals=[],
            )

        from soveryn.agents.heartbeat.thoughts_log import ThoughtsLog
        rec = ThoughtsLog(tlog_path).last()
        assert rec is not None, "ThoughtsLog must be written even for NO_OP"


# ── Test 5: zero-delta → "Environment static" single-line in prompt ───────────


class TestZeroDeltaPrompt:
    def test_static_environment_instruction_in_prompt(self, tmp_path):
        """When current snapshot == prev snapshot, prompt must include
        'Environment static. No new signals.' and NOT ask to re-summarize."""
        from soveryn.agents.heartbeat.thoughts_log import ThoughtsLog
        from soveryn.agents.heartbeat.prompt import build_heartbeat_prompt

        # Build a snapshot identical to what the daemon would produce.
        # We seed the thoughts-log with an identical prior record.
        tlog_path = tmp_path / "thoughts.jsonl"
        tlog = ThoughtsLog(tlog_path)

        # A representative snapshot (board all-zero, no material signals, quiet lattice).
        prior_snapshot = {
            "board": {
                "open_signal_count": 0,
                "open_blueprint_count": 2,
                "ready_blueprint_count": 0,
                "open_friction_count": 0,
                "stalled_blueprint_count": 0,
                "blocked_blueprint_count": 0,
                "oldest_open_signal_age_minutes": None,
                "oldest_open_blueprint_title": "Some Blueprint",
                "oldest_open_blueprint_age_hours": 10,
            },
            "material_signals": [],
            "lattice": {
                "new_node_count_recent_window": 0,
                "recent_window_minutes": 60,
                "new_contradiction_flag_count": 0,
            },
        }
        # Seed the thoughts-log with a prior record holding this snapshot.
        tlog.append({
            "pulse_id": "prev-001",
            "ts": "2026-06-22T13:00:00",
            "snapshot": prior_snapshot,
            "material_signals": [],
            "delta": {"changed": False, "items": []},
            "decision": "NO_OP",
            "rationale": "nothing to surface",
            "surfaced": False,
        })

        # Now build the prompt as the daemon would, with the same snapshot
        # and delta={"changed": False, "items": []}.
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
        assert "Environment static" in prompt, (
            f"Expected 'Environment static' in prompt when delta.changed=False, "
            f"got:\n{prompt}"
        )
        assert "No new signals" in prompt, (
            f"Expected 'No new signals' in prompt when delta.changed=False"
        )

    def test_no_static_instruction_when_delta_changed(self, tmp_path):
        """When delta.changed=True, the static-environment line must NOT appear."""
        from soveryn.agents.heartbeat.prompt import build_heartbeat_prompt

        board = BoardSnapshot(
            open_signal_count=1,
            open_blueprint_count=2,
            ready_blueprint_count=0,
            open_friction_count=0,
            stalled_blueprint_count=0,
            blocked_blueprint_count=0,
            oldest_open_signal_age_minutes=None,
            oldest_open_blueprint_title=None,
            oldest_open_blueprint_age_hours=None,
        )
        lattice = LatticeSnapshot(
            new_node_count_recent_window=3,
            recent_window_minutes=60,
            new_contradiction_flag_count=0,
        )
        prompt = build_heartbeat_prompt(
            minutes_since_last_heartbeat=60,
            board=board,
            lattice=lattice,
            material_signals=[],
            delta={"changed": True, "items": ["open signal count changed: 0 → 1"]},
        )
        assert "Environment static" not in prompt


# ── Test 6: snapshot round-trip — second pulse reads first's snapshot ──────────


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

        # Pulse 1 — model says SURFACE, board has 2 open blueprints.
        with patch.object(d, "_surface_to_primary_thread"):
            _run_tick_with_fakes(
                d,
                model_response="Something important.\n[SURFACE]",
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
        with patch.object(d, "_surface_to_primary_thread"):
            _run_tick_with_fakes(
                d,
                model_response="OK.\n[NO_OP]",
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


# ── Test 7: prompt material_signals rendering ─────────────────────────────────


class TestPromptMaterialSignalsRendering:
    """Directly test build_heartbeat_prompt with the new kwargs."""

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
        """When material_signals non-empty, their details appear prominently."""
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

    def test_material_no_op_disabled_framing_in_prompt(self):
        """With material signals, prompt says [NO_OP] is disabled."""
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
        # NO_OP must be disabled when material signals are present
        assert "NO_OP" in prompt
        assert "disabled" in prompt.lower() or "MATERIAL" in prompt

    def test_non_material_retains_no_op_allowed_framing(self):
        """Without material signals, [NO_OP] is still a valid option."""
        from soveryn.agents.heartbeat.prompt import build_heartbeat_prompt
        prompt = build_heartbeat_prompt(
            minutes_since_last_heartbeat=30,
            board=self._board(),
            lattice=self._lattice(),
            material_signals=[],
            delta={"changed": False, "items": []},
        )
        assert "[NO_OP]" in prompt

    def test_confidence_tiering_note_in_non_material_prompt(self):
        """Non-material prompt should include confidence tiering guidance:
        Objective→surface / Pattern≥3-nodes→surface / Ambient→thoughts-log."""
        from soveryn.agents.heartbeat.prompt import build_heartbeat_prompt
        prompt = build_heartbeat_prompt(
            minutes_since_last_heartbeat=30,
            board=self._board(),
            lattice=self._lattice(),
            material_signals=[],
            delta={"changed": True, "items": ["board changed"]},
        )
        # Tiering note should reference the three tiers
        lower = prompt.lower()
        assert "objective" in lower or "pattern" in lower or "ambient" in lower, (
            f"Expected confidence-tiering note (Objective/Pattern/Ambient) in prompt"
        )
