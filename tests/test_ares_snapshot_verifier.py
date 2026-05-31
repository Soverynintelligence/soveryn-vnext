"""Tests for the Ares snapshot verifier."""

from __future__ import annotations

from soveryn.agents.ares import snapshot as snap
from soveryn.agents.ares.findings import AresFinding, Severity


def _finding(finding_type: str, severity: Severity, key: str = "k") -> AresFinding:
    return AresFinding(finding_type, severity, {"source": finding_type}, key=key)


def test_gate_exit_code_returns_zero_for_clean_snapshot():
    report = snap.SnapshotReport(findings=())
    assert snap.gate_exit_code(report) == 0


def test_gate_exit_code_blocks_on_critical_and_emergency_only():
    report = snap.SnapshotReport(findings=(
        _finding("network.loopback_listener_unallowlisted", Severity.WARNING),
        _finding("network.service_missing", Severity.CRITICAL),
        _finding("network.public_listener_unallowlisted", Severity.EMERGENCY),
    ))
    assert snap.gate_exit_code(report) == 1


def test_format_report_groups_by_severity_and_mentions_findings():
    report = snap.SnapshotReport(findings=(
        _finding("network.public_listener_unallowlisted", Severity.EMERGENCY, key="public"),
        _finding("network.service_missing", Severity.CRITICAL, key="missing"),
        _finding("network.loopback_listener_unallowlisted", Severity.WARNING, key="loop"),
    ))
    text = snap.format_report(report)
    assert "# Ares snapshot" in text
    assert "## EMERGENCY (1)" in text
    assert "## CRITICAL (1)" in text
    assert "## WARNING (1)" in text
    assert "network.public_listener_unallowlisted" in text
    assert "network.service_missing" in text
    assert "network.loopback_listener_unallowlisted" in text


def test_format_report_includes_none_sections_for_missing_severities():
    report = snap.SnapshotReport(findings=(
        _finding("network.loopback_listener_unallowlisted", Severity.WARNING, key="loop"),
    ))
    text = snap.format_report(report)
    assert "## EMERGENCY (0)" in text
    assert "## CRITICAL (0)" in text
    assert "- None" in text


def test_collect_live_snapshot_combines_network_and_architecture(monkeypatch):
    monkeypatch.setattr(snap, "collect_network_live", lambda: [
        _finding("network.loopback_listener_unallowlisted", Severity.WARNING, key="n1"),
    ])
    monkeypatch.setattr(snap, "collect_architecture_live", lambda: [
        _finding("architecture.raw_io_in_agents", Severity.WARNING, key="a1"),
    ])
    report = snap.collect_live_snapshot()
    assert [f.finding_type for f in report.findings] == [
        "network.loopback_listener_unallowlisted",
        "architecture.raw_io_in_agents",
    ]


def test_main_prints_markdown_and_returns_gate_exit_code_for_clean_and_blocked(monkeypatch, capsys):
    monkeypatch.setattr(snap, "collect_live_snapshot", lambda: snap.SnapshotReport(findings=()))
    rc_clean = snap.main([])
    clean_out = capsys.readouterr().out
    assert rc_clean == 0
    assert "- EMERGENCY/CRITICAL gate: clear" in clean_out

    blocked = snap.SnapshotReport(findings=(
        _finding("network.service_missing", Severity.CRITICAL, key="missing"),
    ))
    monkeypatch.setattr(snap, "collect_live_snapshot", lambda: blocked)
    rc_blocked = snap.main([])
    blocked_out = capsys.readouterr().out
    assert rc_blocked == 1
    assert "network.service_missing" in blocked_out
    assert "- EMERGENCY/CRITICAL gate: blocked" in blocked_out
