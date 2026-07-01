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
