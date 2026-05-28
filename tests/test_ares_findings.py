"""Tests for Ares finding identity and lifecycle tracking."""

from __future__ import annotations

import json

from soveryn.agents.ares.daemon import AresFinding as CompatAresFinding
from soveryn.agents.ares.findings import AresFinding, FindingTracker, Severity


def test_severity_enum_has_four_ordered_tiers():
    assert [severity.value for severity in Severity] == [
        "info",
        "warning",
        "critical",
        "emergency",
    ]
    assert Severity.INFO.name == "INFO"
    assert Severity.WARNING.name == "WARNING"
    assert Severity.CRITICAL.name == "CRITICAL"
    assert Severity.EMERGENCY.name == "EMERGENCY"


def test_ares_finding_keeps_shape_and_stable_id():
    finding = AresFinding(
        "gpu.temperature",
        Severity.WARNING,
        {"gpu": 0, "temp_c": 84},
        key="gpu0",
    )
    same_condition = AresFinding(
        "gpu.temperature",
        "warning",
        {"gpu": 0, "temp_c": 86},
        key="gpu0",
    )
    different_key = AresFinding(
        "gpu.temperature",
        Severity.WARNING,
        {"gpu": 1, "temp_c": 84},
        key="gpu1",
    )

    assert finding.finding_type == "gpu.temperature"
    assert finding.severity is Severity.WARNING
    assert finding.evidence == {"gpu": 0, "temp_c": 84}
    assert finding.key == "gpu0"
    assert finding.id == same_condition.id
    assert finding.id != different_key.id


def test_daemon_reexports_ares_finding_for_compatibility():
    finding = CompatAresFinding("filesystem", "low", {"path": "/tmp"})

    assert isinstance(finding, AresFinding)
    assert finding.finding_type == "filesystem"
    assert finding.severity == "low"
    assert finding.evidence == {"path": "/tmp"}


def test_tracker_marks_new_findings_once_and_persists_state(tmp_path):
    state_path = tmp_path / "ares_daemon_state.json"
    first = AresFinding("gpu.temperature", Severity.WARNING, {"gpu": 0}, key="gpu0")
    tracker = FindingTracker(state_path)

    first_cycle = tracker.update([first])
    second_cycle = tracker.update([first])
    reloaded_cycle = FindingTracker(state_path).update([first])

    assert [event.finding.id for event in first_cycle.active] == [first.id]
    assert first_cycle.active[0].is_new is True
    assert second_cycle.active[0].is_new is False
    assert reloaded_cycle.active[0].is_new is False
    assert json.loads(state_path.read_text())["seen_finding_ids"] == [first.id]


def test_tracker_emits_cleared_events_when_seen_finding_disappears(tmp_path):
    state_path = tmp_path / "ares_daemon_state.json"
    gpu = AresFinding("gpu.temperature", Severity.WARNING, {"gpu": 0}, key="gpu0")
    disk = AresFinding("disk.smart", Severity.CRITICAL, {"disk": "nvme0n1"}, key="nvme0n1")
    tracker = FindingTracker(state_path)

    tracker.update([gpu, disk])
    result = tracker.update([gpu])

    assert [event.finding.id for event in result.active] == [gpu.id]
    assert result.active[0].is_new is False
    assert [event.finding.id for event in result.cleared] == [disk.id]
    assert result.cleared[0].finding.finding_type == "disk.smart"
    assert result.cleared[0].is_new is False
    assert json.loads(state_path.read_text())["seen_finding_ids"] == [gpu.id]


def test_tracker_reconstructs_cleared_findings_after_reinstantiation(tmp_path):
    state_path = tmp_path / "ares_daemon_state.json"
    finding = AresFinding("cpu.mce", Severity.CRITICAL, {"socket": 0}, key="socket0")

    FindingTracker(state_path).update([finding])
    result = FindingTracker(state_path).update([])

    assert result.active == ()
    assert len(result.cleared) == 1
    assert result.cleared[0].finding.id == finding.id
    assert result.cleared[0].finding.finding_type == "cpu.mce"
    assert result.cleared[0].finding.severity is Severity.CRITICAL
    assert result.cleared[0].finding.evidence == {"socket": 0}
    assert json.loads(state_path.read_text())["seen_finding_ids"] == []


def test_tracker_default_state_path_is_overridable_by_env(monkeypatch, tmp_path):
    state_path = tmp_path / "state" / "ares_daemon_state.json"
    monkeypatch.setenv("SOVERYN_ARES_STATE_PATH", str(state_path))
    finding = AresFinding("gpu.temperature", Severity.WARNING, {"gpu": 0}, key="gpu0")

    FindingTracker().update([finding])

    assert state_path.exists()
    assert json.loads(state_path.read_text())["seen_finding_ids"] == [finding.id]
