"""Tests for T6 stall lane re-tune: deploy amnesty + worst-first cap.

Pure function tests (hours_since_deploy injected; no DB or wall-clock access).
Deploy clock tests use tmp_path (pytest fixture) for filesystem isolation.

Test command:
    cd /home/jon-deoliveira/soveryn_vnext && \
        ~/miniconda3/envs/soveryn/bin/python -m pytest \
        tests/test_heartbeat_stall_retune.py tests/test_heartbeat_materiality.py -v
"""

from datetime import datetime, timezone
from pathlib import Path

from soveryn.agents.heartbeat.materiality import (
    detect_materiality,
    get_deploy_started_at,
)

NOW = datetime(2026, 6, 28, 12, 0, 0)


# ── Amnesty window tests (hours_since_deploy < 72) ───────────────────────────

def test_amnesty_active_node_that_crossed_48h_during_window_is_material():
    """A node that was <48h old at deploy and crossed 48h during the window
    should be flagged (it's a fresh stall, not a pre-existing one).

    Setup: deploy happened 10h ago (hours_since_deploy=10).
    Node age is 55h → at deploy it was 55 - 10 = 45h (<48), so it crossed
    the threshold mid-window. Should be flagged.
    """
    stalls = [{"ref": "FreshTask", "status": "Open", "age_hours": 55.0}]
    sigs = detect_materiality(
        dated_items=[],
        error_items=[],
        stall_items=stalls,
        now=NOW,
        hours_since_deploy=10.0,
    )
    assert any(s.kind == "stall" and "FreshTask" in s.ref for s in sigs), (
        "Node that crossed 48h during amnesty window should be material"
    )


def test_amnesty_active_node_already_stale_at_deploy_is_suppressed():
    """A node that was already >48h stale when the deploy happened should be
    suppressed during the amnesty window (pre-existing neglect, not new).

    Setup: deploy happened 10h ago (hours_since_deploy=10).
    Node age is 100h → at deploy it was 100 - 10 = 90h (>48). Already stale.
    Should be suppressed.
    """
    stalls = [{"ref": "OldTask", "status": "Open", "age_hours": 100.0}]
    sigs = detect_materiality(
        dated_items=[],
        error_items=[],
        stall_items=stalls,
        now=NOW,
        hours_since_deploy=10.0,
    )
    assert not any(s.kind == "stall" and "OldTask" in s.ref for s in sigs), (
        "Node already stale at deploy should be suppressed during amnesty"
    )


def test_amnesty_active_node_exactly_at_boundary_suppressed():
    """Edge case: age_hours - hours_since_deploy == 48 means it was exactly
    at the threshold at deploy — treat as pre-existing (suppress).

    age_hours=58, hours_since_deploy=10 → age at deploy = 48 (not <48, so suppress).
    """
    stalls = [{"ref": "BoundaryTask", "status": "Open", "age_hours": 58.0}]
    sigs = detect_materiality(
        dated_items=[],
        error_items=[],
        stall_items=stalls,
        now=NOW,
        hours_since_deploy=10.0,
    )
    assert not any(s.kind == "stall" for s in sigs), (
        "Node at exactly 48h at deploy time should be suppressed (not strictly <48)"
    )


def test_amnesty_active_node_under_48h_not_flagged_regardless():
    """A node under 48h is not a stall at all — should never be flagged,
    amnesty or not."""
    stalls = [{"ref": "YoungTask", "status": "Open", "age_hours": 30.0}]
    sigs = detect_materiality(
        dated_items=[],
        error_items=[],
        stall_items=stalls,
        now=NOW,
        hours_since_deploy=10.0,
    )
    assert sigs == [], "Node under 48h should not be flagged"


def test_amnesty_mixed_batch_only_new_crosses_flagged():
    """Two nodes: one crossed 48h during the window (flag it), one was already
    stale at deploy (suppress it)."""
    stalls = [
        {"ref": "CrossedMidWindow", "status": "Open", "age_hours": 55.0},  # age@deploy=45 <48
        {"ref": "AlreadyStale",     "status": "Open", "age_hours": 100.0}, # age@deploy=90 >48
    ]
    sigs = detect_materiality(
        dated_items=[],
        error_items=[],
        stall_items=stalls,
        now=NOW,
        hours_since_deploy=10.0,
    )
    refs = [s.ref for s in sigs if s.kind == "stall"]
    assert "CrossedMidWindow" in refs, "Newly-crossed node should be flagged"
    assert "AlreadyStale" not in refs, "Pre-existing stale node should be suppressed"


# ── Post-amnesty (hours_since_deploy >= 72) tests ────────────────────────────

def test_post_amnesty_7_stale_nodes_returns_3_oldest():
    """After amnesty, when >5 nodes are stale, only the top 3 oldest are returned."""
    stalls = [
        {"ref": f"Node{i}", "status": "Open", "age_hours": float(50 + i * 10)}
        for i in range(7)  # age_hours: 50, 60, 70, 80, 90, 100, 110
    ]
    sigs = detect_materiality(
        dated_items=[],
        error_items=[],
        stall_items=stalls,
        now=NOW,
        hours_since_deploy=100.0,  # post-amnesty
    )
    stall_sigs = [s for s in sigs if s.kind == "stall"]
    assert len(stall_sigs) == 3, f"Expected 3 stall signals, got {len(stall_sigs)}"
    # Should be the 3 oldest: Node6(110h), Node5(100h), Node4(90h)
    refs = {s.ref for s in stall_sigs}
    assert "Node6" in refs, "Oldest node (110h) should be included"
    assert "Node5" in refs, "2nd oldest node (100h) should be included"
    assert "Node4" in refs, "3rd oldest node (90h) should be included"


def test_post_amnesty_4_stale_nodes_all_returned():
    """After amnesty, when <=5 nodes are stale, all are returned (no cap applied)."""
    stalls = [
        {"ref": f"Node{i}", "status": "Open", "age_hours": float(50 + i * 10)}
        for i in range(4)  # 4 nodes: 50, 60, 70, 80 hours
    ]
    sigs = detect_materiality(
        dated_items=[],
        error_items=[],
        stall_items=stalls,
        now=NOW,
        hours_since_deploy=100.0,  # post-amnesty
    )
    stall_sigs = [s for s in sigs if s.kind == "stall"]
    assert len(stall_sigs) == 4, f"Expected 4 stall signals (<=5, no cap), got {len(stall_sigs)}"


def test_post_amnesty_exactly_5_stale_nodes_all_returned():
    """Boundary: exactly 5 stale nodes — no cap (cap triggers only for >5)."""
    stalls = [
        {"ref": f"Node{i}", "status": "Open", "age_hours": float(50 + i * 10)}
        for i in range(5)  # 5 nodes
    ]
    sigs = detect_materiality(
        dated_items=[],
        error_items=[],
        stall_items=stalls,
        now=NOW,
        hours_since_deploy=100.0,
    )
    stall_sigs = [s for s in sigs if s.kind == "stall"]
    assert len(stall_sigs) == 5, f"Expected 5 (no cap at exactly 5), got {len(stall_sigs)}"


def test_post_amnesty_6_stale_nodes_returns_3_oldest():
    """Exactly 6 nodes (>5 trigger) → 3 oldest returned."""
    stalls = [
        {"ref": f"Node{i}", "status": "Open", "age_hours": float(50 + i * 10)}
        for i in range(6)  # 50, 60, 70, 80, 90, 100
    ]
    sigs = detect_materiality(
        dated_items=[],
        error_items=[],
        stall_items=stalls,
        now=NOW,
        hours_since_deploy=100.0,
    )
    stall_sigs = [s for s in sigs if s.kind == "stall"]
    assert len(stall_sigs) == 3


def test_post_amnesty_oldest_3_correct_order():
    """The 3 returned are the top-3 by age_hours descending."""
    stalls = [
        {"ref": "Alpha",   "status": "Open", "age_hours": 200.0},
        {"ref": "Beta",    "status": "Open", "age_hours": 150.0},
        {"ref": "Gamma",   "status": "Open", "age_hours": 120.0},
        {"ref": "Delta",   "status": "Open", "age_hours": 75.0},
        {"ref": "Epsilon", "status": "Open", "age_hours": 60.0},
        {"ref": "Zeta",    "status": "Open", "age_hours": 55.0},
    ]
    sigs = detect_materiality(
        dated_items=[],
        error_items=[],
        stall_items=stalls,
        now=NOW,
        hours_since_deploy=100.0,
    )
    stall_sigs = [s for s in sigs if s.kind == "stall"]
    refs = {s.ref for s in stall_sigs}
    assert refs == {"Alpha", "Beta", "Gamma"}, f"Wrong top-3: {refs}"


# ── Legacy / None behavior (Task 1 backward compat) ─────────────────────────

def test_legacy_none_hours_since_deploy_all_stale_flagged():
    """hours_since_deploy=None → legacy behavior: all >48h stalls flagged, no cap."""
    stalls = [
        {"ref": f"Node{i}", "status": "Open", "age_hours": float(50 + i)}
        for i in range(10)  # 10 nodes all >48h
    ]
    sigs = detect_materiality(
        dated_items=[],
        error_items=[],
        stall_items=stalls,
        now=NOW,
        hours_since_deploy=None,  # explicit None = legacy
    )
    stall_sigs = [s for s in sigs if s.kind == "stall"]
    assert len(stall_sigs) == 10, (
        f"Legacy mode should flag all 10 stale nodes, got {len(stall_sigs)}"
    )


def test_legacy_no_hours_since_deploy_param_all_stale_flagged():
    """Calling detect_materiality without hours_since_deploy defaults to legacy
    behavior — Task 1 test suite stays green."""
    stalls = [{"ref": "Lattice-Librarian", "status": "Open", "age_hours": 342}]
    sigs = detect_materiality(dated_items=[], error_items=[], stall_items=stalls, now=NOW)
    assert any(s.kind == "stall" and "Librarian" in s.ref for s in sigs), (
        "Default (no hours_since_deploy) should flag stalls >48h (Task 1 compat)"
    )


def test_legacy_stall_under_48h_still_not_flagged():
    """Regression: even in legacy mode, sub-48h stalls are not flagged."""
    stalls = [{"ref": "y", "status": "Open", "age_hours": 12}]
    assert detect_materiality(dated_items=[], error_items=[], stall_items=stalls, now=NOW) == []


# ── Deploy clock tests ───────────────────────────────────────────────────────

def test_deploy_clock_first_call_writes_and_returns_now(tmp_path):
    """First call to get_deploy_started_at writes the sentinel and returns `now`."""
    sentinel = tmp_path / "heartbeat_deploy_started_at"
    now = datetime(2026, 6, 29, 8, 0, 0)

    result = get_deploy_started_at(sentinel, now)

    assert result == now, f"Expected {now}, got {result}"
    assert sentinel.exists(), "Sentinel file should have been created"


def test_deploy_clock_second_call_returns_same_ts(tmp_path):
    """Second call returns the persisted timestamp, not the new `now`."""
    sentinel = tmp_path / "heartbeat_deploy_started_at"
    first_now = datetime(2026, 6, 29, 8, 0, 0)
    second_now = datetime(2026, 6, 29, 20, 0, 0)  # 12h later

    get_deploy_started_at(sentinel, first_now)
    result = get_deploy_started_at(sentinel, second_now)

    assert result == first_now, (
        f"Second call should return persisted first_now={first_now}, got {result}"
    )


def test_deploy_clock_idempotent_many_calls(tmp_path):
    """Multiple calls always return the same timestamp as the first call."""
    sentinel = tmp_path / "heartbeat_deploy_started_at"
    original_now = datetime(2026, 6, 29, 8, 0, 0)

    get_deploy_started_at(sentinel, original_now)
    for offset_hours in range(1, 10):
        later = datetime(2026, 6, 29, 8 + offset_hours, 0, 0)
        result = get_deploy_started_at(sentinel, later)
        assert result == original_now, (
            f"Call at offset +{offset_hours}h should still return original_now"
        )


def test_deploy_clock_parent_dir_created(tmp_path):
    """get_deploy_started_at creates parent directories if they don't exist."""
    sentinel = tmp_path / "subdir" / "nested" / "heartbeat_deploy_started_at"
    now = datetime(2026, 6, 29, 8, 0, 0)

    result = get_deploy_started_at(sentinel, now)

    assert result == now
    assert sentinel.exists()


def test_deploy_clock_persisted_ts_survives_parse_roundtrip(tmp_path):
    """The serialized timestamp round-trips through ISO format without precision loss."""
    sentinel = tmp_path / "heartbeat_deploy_started_at"
    # Use a timestamp with seconds precision (common for datetime.now())
    now = datetime(2026, 6, 29, 14, 30, 45)

    get_deploy_started_at(sentinel, now)
    # Simulate a fresh process reading the file
    result = get_deploy_started_at(sentinel, datetime(2026, 6, 30, 0, 0, 0))

    assert result == now, f"Roundtrip failed: expected {now}, got {result}"
