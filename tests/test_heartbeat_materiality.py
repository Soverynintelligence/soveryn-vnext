"""Pure-function tests for heartbeat materiality detector.

detect_materiality is deterministic (no wall-clock, no DB), so all tests
use an injected NOW constant. Data sourcing is handled separately by
_gather_material_signals in the daemon.
"""

from datetime import datetime, timedelta
from soveryn.agents.heartbeat.materiality import detect_materiality, MaterialSignal

NOW = datetime(2026, 6, 28, 12, 0, 0)


def test_deadline_within_7_days_is_material():
    items = [{"ref": "NC-Incentive", "detail": "NC Incentive", "date": NOW + timedelta(days=2)}]
    sig = detect_materiality(dated_items=items, error_items=[], stall_items=[], now=NOW)
    assert any(s.kind == "deadline" and "NC Incentive" in s.detail for s in sig)


def test_deadline_beyond_7_days_not_material():
    items = [{"ref": "x", "detail": "far", "date": NOW + timedelta(days=30)}]
    assert detect_materiality(dated_items=items, error_items=[], stall_items=[], now=NOW) == []


def test_error_code_is_material():
    errs = [{"ref": "Scotty", "text": "dispatch returned 500"}]
    sig = detect_materiality(dated_items=[], error_items=errs, stall_items=[], now=NOW)
    assert any(s.kind == "failure" for s in sig)


def test_stall_over_48h_is_material():
    stalls = [{"ref": "Lattice-Librarian", "status": "Open", "age_hours": 342}]
    sig = detect_materiality(dated_items=[], error_items=[], stall_items=stalls, now=NOW)
    assert any(s.kind == "stall" and "Librarian" in s.ref for s in sig)


def test_stall_under_48h_not_material():
    stalls = [{"ref": "y", "status": "Open", "age_hours": 12}]
    assert detect_materiality(dated_items=[], error_items=[], stall_items=stalls, now=NOW) == []


def test_clean_context_flags_nothing():
    assert detect_materiality(dated_items=[], error_items=[], stall_items=[], now=NOW) == []
