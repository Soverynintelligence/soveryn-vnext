"""Grant-compliance store layer — config loader, submission persistence, done-overlay.

Pure module: stdlib + steward engine only. No LLM, no cognition/lattice/persona imports.
Anti-confab / never-silently-drop discipline:
  - load_grants: unknown cadence raises ValueError (a typo'd cadence producing zero deadlines
    is a hidden missed filing — reject loudly).
  - apply_submissions: pure, never invents submissions, only flips obligations whose key
    (award_id, due_date.isoformat()) is present in the submissions dict.
"""
from __future__ import annotations

import dataclasses
import json
from datetime import date
from typing import Any

from soveryn.platform.steward.engine import Grant, GrantObligation

VALID_CADENCES: frozenset[str] = frozenset({"annual", "quarterly", "final", "milestone"})

# Manual, award-level pipeline states for a submitted APPLICATION (not a report).
# applied = submitted, awaiting funder decision; pending = awaiting more info.
# Both are non-actionable "waiting" states: exempt from overdue rendering and surfacing.
VALID_MANUAL_STATUSES: frozenset[str] = frozenset({"applied", "pending"})

# Keywords that clear a manual override, restoring the date-computed status.
CLEAR_STATUS_KEYWORDS: frozenset[str] = frozenset({"auto", "", "clear", "none"})


# ---------------------------------------------------------------------------
# load_grants
# ---------------------------------------------------------------------------

def load_grants(config_path: str) -> list[Grant]:
    """Read a JSON grants config file and return a list of Grant objects.

    Each entry is a dict with at minimum:
        funder, award_id, title, period_start (ISO), period_end (ISO), reporting_cadence

    Optional fields:
        milestones  — list of [iso_date_str, description] pairs; defaults to []
        award_amount — float or null

    Raises ValueError if reporting_cadence is not in VALID_CADENCES, naming the bad value
    and the award_id so the caller knows exactly which entry to fix.
    """
    with open(config_path, encoding="utf-8") as fh:
        raw: list[dict[str, Any]] = json.load(fh)

    grants: list[Grant] = []
    for entry in raw:
        award_id = entry["award_id"]
        cadence = entry["reporting_cadence"]
        if cadence not in VALID_CADENCES:
            raise ValueError(
                f"Unknown reporting_cadence {cadence!r} for award_id {award_id!r}. "
                f"Valid values: {sorted(VALID_CADENCES)}"
            )

        raw_milestones = entry.get("milestones") or []
        milestones: tuple[tuple[str, str], ...] = tuple(
            (str(m[0]), str(m[1])) for m in raw_milestones
        )

        grants.append(Grant(
            funder=entry["funder"],
            award_id=award_id,
            title=entry["title"],
            period_start=date.fromisoformat(entry["period_start"]),
            period_end=date.fromisoformat(entry["period_end"]),
            reporting_cadence=cadence,
            milestones=milestones,
            award_amount=entry.get("award_amount"),
        ))
    return grants


# ---------------------------------------------------------------------------
# SubmissionStore
# ---------------------------------------------------------------------------

class SubmissionStore:
    """Persists grant submission records to a JSON file.

    Storage format (on disk):
        { "<award_id>|<report_due_iso>": {"submitted_at": "<iso>", "note": "<str>"}, ... }

    all() returns a dict keyed by (award_id, report_due_iso) tuple with the same value
    dicts, with "submitted_at" parsed to a date object.
    """

    def __init__(self, path: str) -> None:
        self._path = path
        self._data: dict[str, dict[str, str]] = self._load()

    def _load(self) -> dict[str, dict[str, str]]:
        try:
            with open(self._path, encoding="utf-8") as fh:
                return json.load(fh)
        except FileNotFoundError:
            return {}

    def _save(self) -> None:
        with open(self._path, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=2)

    def record(self, award_id: str, report_due: date, note: str = "") -> None:
        """Record (or update) a submission for the given obligation.

        Re-recording the same (award_id, report_due) updates the entry.
        submitted_at is always set to today's date at the time of recording.
        """
        key = f"{award_id}|{report_due.isoformat()}"
        self._data[key] = {
            "submitted_at": date.today().isoformat(),
            "note": note,
        }
        self._save()

    def all(self) -> dict[tuple[str, str], dict]:
        """Return all recorded submissions.

        Returns a dict keyed by (award_id, report_due_iso) tuples.
        Each value dict contains "submitted_at" (date object) and "note" (str).
        """
        result: dict[tuple[str, str], dict] = {}
        for raw_key, val in self._data.items():
            award_id, due_iso = raw_key.split("|", 1)
            result[(award_id, due_iso)] = {
                "submitted_at": date.fromisoformat(val["submitted_at"]),
                "note": val.get("note", ""),
            }
        return result


# ---------------------------------------------------------------------------
# StatusStore — award-level manual pipeline overrides (applied/pending)
# ---------------------------------------------------------------------------

class StatusStore:
    """Persists award-level manual status overrides to a JSON file.

    Keyed by award_id (not per-obligation): a submitted APPLICATION is a single
    pipeline fact about the whole award, so the override overlays every obligation
    of that grant.

    Storage format (on disk):
        { "<award_id>": {"status": "applied"|"pending", "set_at": "<iso>", "note": "<str>"}, ... }

    all() returns a dict keyed by award_id with "set_at" parsed to a date object.
    """

    def __init__(self, path: str) -> None:
        self._path = path
        self._data: dict[str, dict[str, str]] = self._load()

    def _load(self) -> dict[str, dict[str, str]]:
        try:
            with open(self._path, encoding="utf-8") as fh:
                return json.load(fh)
        except FileNotFoundError:
            return {}

    def _save(self) -> None:
        with open(self._path, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=2)

    def set(self, award_id: str, status: str, note: str = "") -> None:
        """Set (or update) the manual override for a grant.

        set_at is stamped to today's date at the time of recording.
        Does NOT validate status — use set_grant_status for the validated write path.
        """
        self._data[award_id] = {
            "status": status,
            "set_at": date.today().isoformat(),
            "note": note,
        }
        self._save()

    def clear(self, award_id: str) -> None:
        """Remove any manual override for a grant, restoring the computed status."""
        if award_id in self._data:
            del self._data[award_id]
            self._save()

    def all(self) -> dict[str, dict]:
        """Return all manual overrides keyed by award_id.

        Each value dict contains "status" (str), "set_at" (date object) and "note" (str).
        """
        result: dict[str, dict] = {}
        for award_id, val in self._data.items():
            result[award_id] = {
                "status": val["status"],
                "set_at": date.fromisoformat(val["set_at"]) if val.get("set_at") else None,
                "note": val.get("note", ""),
            }
        return result


def set_grant_status(
    statuses_path: str,
    award_id: str,
    status: str,
    note: str = "",
) -> dict[str, Any]:
    """Validated write path for a manual pipeline status — shared by the tool and HTTP endpoint.

    status in VALID_MANUAL_STATUSES ("applied"/"pending") records the override.
    status in CLEAR_STATUS_KEYWORDS ("auto"/""/"clear"/"none") clears it, restoring
    the date-computed status.

    Raises ValueError (never silently no-ops) on an empty award_id or an unknown status,
    so both callers can surface a precise error. Returns a confirmation dict.
    """
    if not isinstance(award_id, str) or not award_id.strip():
        raise ValueError("award_id must be a non-empty string")
    award_id = award_id.strip()

    status_norm = (status or "").strip().lower()
    store = StatusStore(statuses_path)

    if status_norm in CLEAR_STATUS_KEYWORDS:
        store.clear(award_id)
        return {"ok": True, "award_id": award_id, "status": "auto", "cleared": True}

    if status_norm not in VALID_MANUAL_STATUSES:
        raise ValueError(
            f"status must be one of {sorted(VALID_MANUAL_STATUSES)} "
            f"or 'auto' to clear; got {status!r}"
        )

    if not isinstance(note, str):
        note = str(note)

    store.set(award_id, status_norm, note)
    return {
        "ok": True,
        "award_id": award_id,
        "status": status_norm,
        "set_at": date.today().isoformat(),
        "note": note,
    }


# ---------------------------------------------------------------------------
# apply_submissions — pure overlay
# ---------------------------------------------------------------------------

def apply_submissions(
    obligations: list[GrantObligation],
    submissions: dict[tuple[str, str], dict],
) -> list[GrantObligation]:
    """Pure overlay: return a new list of GrantObligation with matched ones flipped to done.

    An obligation matches a submission when (obligation.award_id, obligation.due_date.isoformat())
    is a key in submissions. Matched obligations get status="done", submitted_at, and note
    populated from the submission. All others are returned unchanged.

    Mutates nothing — uses dataclasses.replace to produce new instances.
    Never invents submissions: an obligation is only marked done if explicitly present in submissions.
    """
    out: list[GrantObligation] = []
    for ob in obligations:
        key = (ob.award_id, ob.due_date.isoformat())
        if key in submissions:
            sub = submissions[key]
            submitted_at_raw = sub.get("submitted_at")
            submitted_at: date | None = (
                date.fromisoformat(submitted_at_raw) if isinstance(submitted_at_raw, str)
                else submitted_at_raw if isinstance(submitted_at_raw, date)
                else None
            )
            out.append(dataclasses.replace(
                ob,
                status="done",
                submitted_at=submitted_at,
                note=sub.get("note", ""),
            ))
        else:
            out.append(ob)
    return out


# ---------------------------------------------------------------------------
# apply_status_overrides — pure overlay (precedence: done > manual > computed)
# ---------------------------------------------------------------------------

def apply_status_overrides(
    obligations: list[GrantObligation],
    overrides: dict[str, dict],
) -> list[GrantObligation]:
    """Pure overlay: apply award-level manual statuses (applied/pending) onto obligations.

    An obligation matches an override when obligation.award_id is a key in overrides.
    Every matched obligation of that grant gets the manual status (and note).

    Precedence is load-bearing: a submission-derived status="done" ALWAYS wins — a
    manual override never un-does a recorded submission. Manual overrides only replace
    date-computed statuses (overdue/upcoming). Apply this AFTER apply_submissions.

    Mutates nothing — uses dataclasses.replace to produce new instances.
    Never invents overrides: only grants explicitly present in overrides are touched.
    """
    out: list[GrantObligation] = []
    for ob in obligations:
        override = overrides.get(ob.award_id)
        if override is not None and ob.status != "done":
            out.append(dataclasses.replace(
                ob,
                status=override["status"],
                note=override.get("note", ob.note),
            ))
        else:
            out.append(ob)
    return out
