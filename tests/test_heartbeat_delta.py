"""Tests for compute_delta — pure delta framing for heartbeat pulses.

compute_delta(current: dict, prev_record: dict | None) -> dict
    Returns {"changed": bool, "items": list[str]}.

current snapshot shape (Task 7 reference):
    {
        "board": {
            "open_signal_count":        int,
            "open_blueprint_count":     int,
            "ready_blueprint_count":    int,
            "open_friction_count":      int,
            "stalled_blueprint_count":  int,
            "blocked_blueprint_count":  int,
            "oldest_open_signal_age_minutes":   int | None,
            "oldest_open_blueprint_title":      str | None,
            "oldest_open_blueprint_age_hours":  int | None,
        },
        "material_signals": [
            {"kind": str, "ref": str, "detail": str},
            ...
        ],
        "lattice": {
            "new_node_count_recent_window":    int,
            "recent_window_minutes":           int,
            "new_contradiction_flag_count":    int,
        },
    }

prev_record carries a "snapshot" key holding the same shape. ThoughtsLog.last()
returns the raw record dict; compute_delta reads prev_record["snapshot"].
"""

from soveryn.agents.heartbeat.delta import compute_delta


# ── helpers ──────────────────────────────────────────────────────────────────


def _make_snapshot(
    *,
    open_signal_count: int = 0,
    open_blueprint_count: int = 2,
    ready_blueprint_count: int = 0,
    open_friction_count: int = 0,
    stalled_blueprint_count: int = 0,
    blocked_blueprint_count: int = 0,
    oldest_open_signal_age_minutes: int | None = None,
    oldest_open_blueprint_title: str | None = None,
    oldest_open_blueprint_age_hours: int | None = None,
    material_signals: list[dict] | None = None,
    new_node_count_recent_window: int = 0,
    recent_window_minutes: int = 60,
    new_contradiction_flag_count: int = 0,
) -> dict:
    return {
        "board": {
            "open_signal_count": open_signal_count,
            "open_blueprint_count": open_blueprint_count,
            "ready_blueprint_count": ready_blueprint_count,
            "open_friction_count": open_friction_count,
            "stalled_blueprint_count": stalled_blueprint_count,
            "blocked_blueprint_count": blocked_blueprint_count,
            "oldest_open_signal_age_minutes": oldest_open_signal_age_minutes,
            "oldest_open_blueprint_title": oldest_open_blueprint_title,
            "oldest_open_blueprint_age_hours": oldest_open_blueprint_age_hours,
        },
        "material_signals": material_signals or [],
        "lattice": {
            "new_node_count_recent_window": new_node_count_recent_window,
            "recent_window_minutes": recent_window_minutes,
            "new_contradiction_flag_count": new_contradiction_flag_count,
        },
    }


def _make_prev_record(snapshot: dict) -> dict:
    """Wrap a snapshot in a ThoughtsLog-shaped record."""
    return {
        "pulse_id": "prev-pulse-1",
        "ts": "2026-06-22T01:00:00Z",
        "material_signals": snapshot["material_signals"],
        "delta": {},
        "decision": "NO_OP",
        "rationale": "nothing changed",
        "surfaced": False,
        "snapshot": snapshot,
    }


# ── 1. identical current vs prev snapshot → changed False, empty items ────────


def test_identical_snapshots_not_changed():
    snap = _make_snapshot(open_blueprint_count=2)
    prev = _make_prev_record(snap)
    result = compute_delta(snap, prev)
    assert result["changed"] is False
    assert result["items"] == []


# ── 2. new material signal vs prev → changed True, signal named in items ─────


def test_new_material_signal_detected():
    prev_snap = _make_snapshot(
        material_signals=[{"kind": "stall", "ref": "Lattice-Librarian", "detail": "stalled 50h"}],
    )
    current_snap = _make_snapshot(
        material_signals=[
            {"kind": "stall", "ref": "Lattice-Librarian", "detail": "stalled 50h"},
            {"kind": "deadline", "ref": "NC-Incentive", "detail": "due in 2 days"},
        ],
    )
    prev = _make_prev_record(prev_snap)
    result = compute_delta(current_snap, prev)
    assert result["changed"] is True
    assert any("NC-Incentive" in item for item in result["items"])


# ── 3. board count change (open_blueprint_count 2→3) → changed True ──────────


def test_board_count_change_detected():
    prev_snap = _make_snapshot(open_blueprint_count=2)
    current_snap = _make_snapshot(open_blueprint_count=3)
    prev = _make_prev_record(prev_snap)
    result = compute_delta(current_snap, prev)
    assert result["changed"] is True
    # At least one item should mention blueprints or open_blueprint_count
    assert any("blueprint" in item.lower() for item in result["items"])


# ── 4. prev_record None → changed True with "first pulse" item (not static) ──


def test_first_pulse_no_prev():
    snap = _make_snapshot()
    result = compute_delta(snap, None)
    assert result["changed"] is True
    assert any("first pulse" in item.lower() for item in result["items"])


# ── additional coverage ───────────────────────────────────────────────────────


def test_removed_signal_not_in_current_not_flagged_as_new():
    """A signal present in prev but gone in current is not a 'new' signal."""
    prev_snap = _make_snapshot(
        material_signals=[{"kind": "stall", "ref": "OldRef", "detail": "stalled"}],
    )
    current_snap = _make_snapshot(material_signals=[])
    prev = _make_prev_record(prev_snap)
    result = compute_delta(current_snap, prev)
    # No new signals — but board is identical so no board change either.
    # The removed signal alone should not produce changed=True.
    # (Delta only surfaces what's NEW, not what's gone — per spec.)
    assert result["changed"] is False
    assert result["items"] == []


def test_friction_count_change_detected():
    prev_snap = _make_snapshot(open_friction_count=0)
    current_snap = _make_snapshot(open_friction_count=1)
    prev = _make_prev_record(prev_snap)
    result = compute_delta(current_snap, prev)
    assert result["changed"] is True


def test_stalled_blueprint_change_detected():
    prev_snap = _make_snapshot(stalled_blueprint_count=0)
    current_snap = _make_snapshot(stalled_blueprint_count=1)
    prev = _make_prev_record(prev_snap)
    result = compute_delta(current_snap, prev)
    assert result["changed"] is True
    assert any("stall" in item.lower() for item in result["items"])
