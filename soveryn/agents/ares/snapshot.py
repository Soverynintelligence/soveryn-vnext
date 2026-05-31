"""Live snapshot verifier for Ares readiness."""

from __future__ import annotations

import argparse
from dataclasses import dataclass

from soveryn.agents.ares.findings import AresFinding, Severity
from soveryn.agents.ares.lanes.architecture import collect_architecture_live
from soveryn.agents.ares.lanes.network import collect_network_live

SEVERITY_ORDER: tuple[Severity, ...] = (
    Severity.EMERGENCY,
    Severity.CRITICAL,
    Severity.WARNING,
    Severity.INFO,
)


@dataclass(frozen=True, slots=True)
class SnapshotReport:
    findings: tuple[AresFinding, ...]

    def grouped(self) -> dict[Severity, tuple[AresFinding, ...]]:
        grouped: dict[Severity, list[AresFinding]] = {severity: [] for severity in SEVERITY_ORDER}
        for finding in self.findings:
            severity = _normalize_severity(finding.severity)
            grouped.setdefault(severity, []).append(finding)
        return {severity: tuple(items) for severity, items in grouped.items() if items}


def collect_live_snapshot() -> SnapshotReport:
    findings = tuple(collect_network_live() + collect_architecture_live())
    return SnapshotReport(findings=findings)


def format_report(report: SnapshotReport) -> str:
    grouped = report.grouped()
    lines = ["# Ares snapshot", ""]
    lines.append(f"- Total findings: {len(report.findings)}")
    lines.append(f"- EMERGENCY/CRITICAL gate: {'blocked' if gate_exit_code(report) else 'clear'}")
    lines.append("")
    for severity in SEVERITY_ORDER:
        items = grouped.get(severity, ())
        lines.append(f"## {severity.value.upper()} ({len(items)})")
        if not items:
            lines.append("- None")
            lines.append("")
            continue
        lines.append("| finding_type | key | evidence |")
        lines.append("| --- | --- | --- |")
        for finding in items:
            lines.append(f"| {finding.finding_type} | {finding.key} | {finding.evidence} |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def gate_exit_code(report: SnapshotReport) -> int:
    for finding in report.findings:
        severity = _normalize_severity(finding.severity)
        if severity in {Severity.EMERGENCY, Severity.CRITICAL}:
            return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m soveryn.agents.ares.snapshot",
        description="Run Ares network and architecture snapshot once and print a markdown report.",
    )
    parser.parse_args(argv)
    report = collect_live_snapshot()
    print(format_report(report), end="")
    return gate_exit_code(report)


def _normalize_severity(severity: Severity | str) -> Severity:
    if isinstance(severity, Severity):
        return severity
    return Severity(str(severity).lower().strip())


if __name__ == "__main__":
    raise SystemExit(main())
