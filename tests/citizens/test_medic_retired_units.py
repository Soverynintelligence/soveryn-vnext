"""Medic retired-units regression guard (blueprint 1f1f049d, 2026-10-22, Forge).

The trap this test exists for, twice over: `systemctl disable --now` does not
hold against the medic. The medic reads a stopped unit as unhealthy and heals
it — tg-bridge came back 42s after its stop, vett-patrol 33s after its. The
watch list (`TARGETS` + `_UNIT_KEYS`) is the only place "deliberately retired"
can live, so a retired unit that reappears there is a live regression.

Source of truth for "retired" is docs/CURRENT_TRUTH.md: any row whose status
cell says DISABLED / STOPPED / retired. If truth marks a unit retired and the
medic still watches it, this test fails.

Acceptance: `python -m pytest tests/citizens/test_medic_retired_units.py -v`
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from soveryn.platform.medic import medic

REPO = Path(__file__).resolve().parents[2]
CURRENT_TRUTH = REPO / "docs" / "CURRENT_TRUTH.md"

RETIRED_MARKERS = ("disabled", "stopped", "retired")
# A unit token: something that looks like a systemd unit name.
UNIT_RE = re.compile(r"\b([a-z0-9][a-z0-9._-]*\.(?:service|timer))\b")


def _retired_units_from_truth() -> set[str]:
    """Unit names that CURRENT_TRUTH marks DISABLED / STOPPED / retired."""
    assert CURRENT_TRUTH.exists(), f"missing {CURRENT_TRUTH}"
    retired: set[str] = set()
    for line in CURRENT_TRUTH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if all(set(c) <= set("-: ") for c in cells):
            continue  # separator row
        lowered = " ".join(cells).lower()
        if not any(marker in lowered for marker in RETIRED_MARKERS):
            continue
        # Only the unit tokens on that row count; prose about other units
        # ("same trap the retired tg-bridge documented") is filtered by the
        # retired-marker requirement above, not by position.
        retired.update(UNIT_RE.findall(stripped))
    return retired


def _medic_watched_units() -> set[str]:
    """Every unit the medic can act on: TARGETS values + _UNIT_KEYS names."""
    watched = {t.unit for t in medic.TARGETS.values()}
    watched.update(medic._UNIT_KEYS)
    return watched


def test_truth_names_at_least_one_retired_unit() -> None:
    """Guard the guard: if this goes empty, the parse broke, not the fleet."""
    retired = _retired_units_from_truth()
    assert retired, (
        "no retired units parsed from CURRENT_TRUTH — the parser or the file "
        "changed shape; fix the parse before trusting the regression check"
    )


def test_medic_does_not_watch_retired_units() -> None:
    retired = _retired_units_from_truth()
    watched = _medic_watched_units()
    overlap = sorted(retired & watched)
    assert not overlap, (
        "medic still watches retired unit(s): "
        f"{overlap}. CURRENT_TRUTH marks these DISABLED/STOPPED/retired; a "
        "stopped unit in TARGETS/_UNIT_KEYS gets healed back to life. Remove "
        "it from soveryn/platform/medic/medic.py (same fix as tg-bridge and "
        "vett-patrol)."
    )


def test_retired_units_absent_from_target_keys() -> None:
    """Key-level check: a retired unit's short name must not be a TARGETS key."""
    retired = _retired_units_from_truth()
    retired_keys = {u.removesuffix(".service").removesuffix(".timer") for u in retired}
    overlap = sorted(retired_keys & set(medic.TARGETS))
    assert not overlap, f"retired unit key(s) still in medic.TARGETS: {overlap}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
