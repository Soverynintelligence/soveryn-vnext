"""Ares finding model and lifecycle tracking."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


DEFAULT_ARES_STATE_PATH = Path("/home/jon-deoliveira/soveryn_vnext/data/ares/ares_daemon_state.json")


class Severity(str, Enum):
    """Ares detection severity tiers."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


@dataclass(frozen=True)
class AresFinding:
    """One host-sentinel condition detected by Ares."""

    finding_type: str
    severity: Severity | str
    evidence: dict[str, Any]
    key: str = ""
    id: str = field(init=False)

    def __post_init__(self) -> None:
        finding_type = self.finding_type.strip()
        if not finding_type:
            raise ValueError("finding_type must be non-empty")
        key = self.key.strip() or _default_key(self.evidence)
        object.__setattr__(self, "finding_type", finding_type)
        object.__setattr__(self, "key", key)
        object.__setattr__(self, "id", f"{finding_type}:{key}")
        if isinstance(self.severity, Severity):
            return
        normalized = str(self.severity).lower().strip()
        try:
            object.__setattr__(self, "severity", Severity(normalized))
        except ValueError:
            # Preserve pre-Phase-3 contract compatibility for legacy callers that
            # instantiated AresFinding with ad-hoc severity strings such as "low".
            object.__setattr__(self, "severity", self.severity)


@dataclass(frozen=True)
class FindingEvent:
    finding: AresFinding
    is_new: bool


@dataclass(frozen=True)
class FindingTrackerResult:
    active: tuple[FindingEvent, ...]
    cleared: tuple[FindingEvent, ...]


class FindingTracker:
    """Durable fire-on-transition tracker for Ares findings."""

    def __init__(self, state_path: Path | None = None) -> None:
        self.state_path = Path(state_path) if state_path is not None else _default_state_path()
        self._state = self._load_state()

    def update(self, findings: list[AresFinding] | tuple[AresFinding, ...]) -> FindingTrackerResult:
        current_by_id = {finding.id: finding for finding in findings}
        previous_ids = set(self._state["seen_finding_ids"])
        current_ids = set(current_by_id)
        previous_findings = self._state["findings"]

        active = tuple(
            FindingEvent(finding, is_new=finding.id not in previous_ids)
            for finding in sorted(current_by_id.values(), key=lambda item: item.id)
        )
        cleared = tuple(
            FindingEvent(_finding_from_record(previous_findings[finding_id]), is_new=False)
            for finding_id in sorted(previous_ids - current_ids)
            if finding_id in previous_findings
        )

        self._state = {
            "seen_finding_ids": sorted(current_ids),
            "findings": {
                finding.id: _finding_to_record(finding)
                for finding in sorted(current_by_id.values(), key=lambda item: item.id)
            },
        }
        self._save_state()
        return FindingTrackerResult(active=active, cleared=cleared)

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"seen_finding_ids": [], "findings": {}}
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"seen_finding_ids": [], "findings": {}}
        seen = raw.get("seen_finding_ids", [])
        findings = raw.get("findings", {})
        if not isinstance(seen, list) or not isinstance(findings, dict):
            return {"seen_finding_ids": [], "findings": {}}
        return {
            "seen_finding_ids": [str(item) for item in seen],
            "findings": findings,
        }

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(self._state, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _default_state_path() -> Path:
    override = os.environ.get("SOVERYN_ARES_STATE_PATH")
    return Path(override) if override else DEFAULT_ARES_STATE_PATH


def _default_key(evidence: dict[str, Any]) -> str:
    try:
        return json.dumps(evidence, sort_keys=True, separators=(",", ":"))
    except TypeError:
        return repr(sorted(evidence.items()))


def _severity_value(severity: Severity | str) -> str:
    return severity.value if isinstance(severity, Severity) else str(severity)


def _finding_to_record(finding: AresFinding) -> dict[str, Any]:
    return {
        "finding_type": finding.finding_type,
        "severity": _severity_value(finding.severity),
        "evidence": finding.evidence,
        "key": finding.key,
    }


def _finding_from_record(record: dict[str, Any]) -> AresFinding:
    return AresFinding(
        str(record["finding_type"]),
        str(record["severity"]),
        dict(record.get("evidence") or {}),
        key=str(record["key"]),
    )
