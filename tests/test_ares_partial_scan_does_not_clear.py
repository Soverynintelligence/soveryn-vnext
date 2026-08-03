"""A collector that fails must not resolve live findings.

`FindingTracker.update()` clears every finding absent from the list it is given.
That is correct when a collector reports "nothing wrong" and catastrophic when a
collector reports nothing *because it could not read*.

Observed 2026-08-02: `gpu.headroom` on a Quadro sitting under 1 GB free flipped
active -> cleared every ~36 minutes with byte-identical evidence, paging Signal
on each transition while Mission Control — which renders active findings only —
stayed empty. `_read_gpu_headroom_rows()` returned `[]` whenever nvidia-smi
exited non-zero, so a single failed probe read as three healthy cards.

The same shape as the incident the honesty papers document: absence of evidence
recorded as evidence of absence.
"""
from __future__ import annotations

import pytest

from soveryn.agents.ares.daemon import AresDaemonSurface
from soveryn.agents.ares.findings import AresFinding, FindingTracker, Severity


def _finding(key: str = "gpu0") -> AresFinding:
    return AresFinding("gpu.headroom", Severity.CRITICAL,
                       {"uuid": key, "free_mb": 942}, key=key)


@pytest.fixture()
def tracker(tmp_path):
    return FindingTracker(state_path=tmp_path / "state.json")


def _daemon(collectors, tracker):
    return AresDaemonSurface(collectors=collectors, tracker=tracker)


def test_healthy_scan_clears_a_resolved_finding(tracker):
    """Baseline: a collector that really does report all-clear still clears."""
    d = _daemon([lambda: (_finding(),)], tracker)
    d.scan_once()
    d.collectors = (lambda: (),)          # genuinely nothing wrong now
    d.scan_once()
    assert tracker._state["seen_finding_ids"] == [], (
        "a successful scan reporting no findings must clear the prior one"
    )


def test_failed_collector_does_not_clear_a_live_finding(tracker):
    """The bug: a raising collector must leave existing findings alone."""
    d = _daemon([lambda: (_finding(),)], tracker)
    d.scan_once()
    seen_before = list(tracker._state["seen_finding_ids"])
    assert seen_before, "precondition: the finding was recorded"

    def boom():
        raise RuntimeError("nvidia-smi exited 9")

    d.collectors = (boom,)
    d.scan_once()

    assert tracker._state["seen_finding_ids"] == seen_before, (
        "a failed collector cleared a live finding — this is the 2026-08-02 "
        "gpu.headroom flap: alert fires, pages Signal, then silently resolves "
        "while the card is still breaching"
    )


def test_one_failure_protects_every_lane(tracker):
    """A partial scan draws no conclusions at all, not just for the failed lane.

    Findings are keyed by id, not by lane, so the tracker cannot know which
    lane owned which finding. Skipping the whole update is the conservative
    reading and errs toward continuing to alert.
    """
    good = lambda: (AresFinding("network.listener", Severity.WARNING, {}, key="n1"),)
    d = _daemon([good, lambda: (_finding(),)], tracker)
    d.scan_once()
    before = list(tracker._state["seen_finding_ids"])
    assert len(before) == 2

    def boom():
        raise RuntimeError("lane down")

    d.collectors = (good, boom)           # the gpu lane fails; network is fine
    d.scan_once()
    assert tracker._state["seen_finding_ids"] == before, (
        "the surviving lane's success must not be used to clear the failed "
        "lane's findings"
    )


def test_gpu_read_failure_raises_rather_than_reporting_health(monkeypatch):
    """The collector-level half: no rows must not read as no problems."""
    from soveryn.agents.ares.lanes import vitals

    class _Result:
        returncode = 9
        stdout = ""
        stderr = "NVML: driver/library version mismatch"

    monkeypatch.setattr(vitals.subprocess, "run", lambda *a, **k: _Result())
    with pytest.raises(vitals.GpuReadError):
        vitals._read_gpu_headroom_rows()


def test_empty_gpu_listing_is_also_a_failure(monkeypatch):
    """nvidia-smi exiting 0 with no rows is a failed read on a box with cards."""
    from soveryn.agents.ares.lanes import vitals

    class _Result:
        returncode = 0
        stdout = "\n"
        stderr = ""

    monkeypatch.setattr(vitals.subprocess, "run", lambda *a, **k: _Result())
    with pytest.raises(vitals.GpuReadError):
        vitals._read_gpu_headroom_rows()
