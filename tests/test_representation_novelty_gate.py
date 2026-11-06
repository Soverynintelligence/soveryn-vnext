"""Tests for the novelty-gate tally (scripts/representation/novelty_gate_check.py)."""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "representation"))
from novelty_gate_check import gate_status  # noqa: E402


def _line(day: date, offered: int, written: int, dry_run: bool = False) -> dict:
    return {
        "ts": datetime(day.year, day.month, day.day, 12).isoformat(),
        "run_id": f"r-{day}-{offered}-{written}",
        "dry_run": dry_run,
        "offered": offered,
        "written": written,
        "skipped_exact": offered - written,
        "skipped_near": 0,
    }


TODAY = date(2026, 11, 5)


def test_pass_window():
    lines = [_line(TODAY - timedelta(days=i), 10, 9) for i in range(7)]
    s = gate_status(lines, today=TODAY)
    assert s["verdict"] == "pass"
    assert s["novelty_ratio"] == 0.9


def test_fail_window():
    lines = [_line(TODAY - timedelta(days=i), 10, 5) for i in range(7)]
    s = gate_status(lines, today=TODAY)
    assert s["verdict"] == "fail"
    assert s["novelty_ratio"] == 0.5


def test_dry_run_lines_ignored():
    lines = [_line(TODAY, 10, 10, dry_run=True) for _ in range(7)]
    s = gate_status(lines, today=TODAY)
    assert s["verdict"] == "insufficient"


def test_insufficient_low_offered():
    lines = [_line(TODAY, 2, 2), _line(TODAY - timedelta(days=1), 2, 2)]
    s = gate_status(lines, today=TODAY)
    assert s["verdict"] == "insufficient"


def test_old_lines_out_of_window():
    old = TODAY - timedelta(days=30)
    lines = [_line(old, 10, 10) for _ in range(7)]
    s = gate_status(lines, today=TODAY)
    assert s["verdict"] == "insufficient"


def test_boundary_exactly_80_percent():
    lines = [_line(TODAY - timedelta(days=i), 10, 8) for i in range(7)]
    s = gate_status(lines, today=TODAY)
    assert s["verdict"] == "pass"
