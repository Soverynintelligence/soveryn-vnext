"""Crash-watch flap guard (2026-10-23, Forge — objective 38f4264d).

The watch file flapped every 15 minutes because `Type=oneshot` units (and the
watch itself) are ActiveState=activating while they run, and the detector
counted that as a break. These tests pin the fix:

- a fresh `activating` oneshot is NOT a problem
- a `activating` unit stuck past the budget IS a problem
- `failed` is still a problem, unchanged
- restart counter threshold unchanged
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "systemd_health_watch.py"


def _load():
    spec = importlib.util.spec_from_file_location("systemd_health_watch", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def watch():
    return _load()


def _props(**overrides) -> dict[str, str]:
    base = {
        "ActiveState": "active",
        "SubState": "running",
        "NRestarts": "0",
        "Result": "success",
        "Type": "oneshot",
        "ActiveEnterTimestampMonotonic": "1000000",  # 1s after boot
    }
    base.update(overrides)
    return base


def test_fresh_activating_oneshot_is_not_a_problem(watch):
    # Watch starts at t=1s; it scans itself at t=2s. Must stay quiet.
    props = _props(ActiveState="activating", SubState="start")
    now_us = 2_000_000
    assert watch.problems_for("soveryn-crash-watch.service", props, now_us) == []


def test_activating_within_budget_is_not_a_problem(watch):
    props = _props(ActiveState="activating", SubState="start")
    now_us = 1_000_000 + (watch.STUCK_ACTIVATING_SECONDS - 1) * 1_000_000
    assert watch.problems_for("soveryn-thermal.service", props, now_us) == []


def test_stuck_activating_is_a_problem(watch):
    props = _props(ActiveState="activating", SubState="start")
    now_us = 1_000_000 + (watch.STUCK_ACTIVATING_SECONDS + 5) * 1_000_000
    found = watch.problems_for("soveryn-thermal.service", props, now_us)
    assert len(found) == 1
    assert "stuck" in found[0]
    assert "soveryn-thermal.service" in found[0]


def test_activating_without_timestamp_is_not_a_problem(watch):
    """Missing/unparseable monotonic stamp must not invent a stuck alarm."""
    props = _props(ActiveState="activating", SubState="start",
                   ActiveEnterTimestampMonotonic="")
    assert watch.problems_for("soveryn-medic.service", props, 10**12) == []


def test_failed_is_still_a_problem(watch):
    props = _props(ActiveState="failed", SubState="failed", Result="exit-code")
    found = watch.problems_for("soveryn-security-sweep.service", props, 10**12)
    assert len(found) == 1
    assert "state=failed" in found[0]


def test_restart_threshold_still_fires(watch):
    props = _props(NRestarts=str(watch.RESTART_THRESHOLD))
    found = watch.problems_for("soveryn-vnext.service", props, 10**12)
    assert len(found) == 1
    assert "restart counter" in found[0]


def test_healthy_unit_is_quiet(watch):
    assert watch.problems_for("soveryn-eyes.service", _props(), 10**12) == []
