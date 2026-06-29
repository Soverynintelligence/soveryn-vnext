"""Steward grant-compliance tools for Aetheria and Vett.

Four ToolSpecs over the deterministic engine + store:
  - grant_deadlines  (read)  — due/overdue/upcoming obligations, done filtered out
  - grant_status     (read)  — all obligations for one award (incl. done)
  - list_grants      (read)  — grant metadata catalogue
  - grant_submit     (write) — narrow audited write; records a submission

Registered for BOTH "aetheria" and "vett". NOT scotty (bounded mechanical surface).

Anti-confab: all read handlers return only engine-computed data, never fabricated dates.
Graceful: if grants config does not yet exist (FileNotFoundError), read tools return
empty results rather than crashing. Keeps startup safe before grants.json exists.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from soveryn.platform.steward.engine import compute_grant_schedule
from soveryn.platform.steward.store import SubmissionStore, apply_submissions, load_grants
from soveryn.platform.tools.registry import ToolArgError, ToolSpec

# Agents that should receive steward tools. NOT scotty.
_STEWARD_OWNERS = ("aetheria", "vett")


# ---------------------------------------------------------------------------
# grant_deadlines
# ---------------------------------------------------------------------------

def build_grant_deadlines_tool(
    *,
    grants_config_path: str,
    submissions_path: str,
    owner_agent: str,
) -> ToolSpec:
    def handler(args: Mapping[str, Any]) -> list[dict[str, Any]]:
        raw_window = args.get("window_days", 90)
        try:
            window_days = int(raw_window)
        except (TypeError, ValueError):
            raise ToolArgError("window_days must be an integer")
        if window_days < 0:
            raise ToolArgError("window_days must be non-negative")

        try:
            grants = load_grants(grants_config_path)
        except FileNotFoundError:
            return []

        store = SubmissionStore(submissions_path)
        submissions = store.all()

        obligations = compute_grant_schedule(
            grants,
            today=date.today(),
            lookback_days=365,
            horizon_days=window_days,
        )
        obligations = apply_submissions(obligations, submissions)

        # Filter out done — only upcoming/overdue shown in this view
        return [
            {
                "award_id": ob.award_id,
                "funder": ob.funder,
                "title": ob.title,
                "report_label": ob.report_label,
                "due_date": ob.due_date.isoformat(),
                "status": ob.status,
            }
            for ob in obligations
            if ob.status != "done"
        ]

    return ToolSpec(
        name="grant_deadlines",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "window_days": {
                    "type": "integer",
                    "description": (
                        "Look-ahead horizon in days. Obligations due within this many "
                        "days (and overdue within 365 days past) are returned. Default 90."
                    ),
                    "default": 90,
                },
            },
            "required": [],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Return upcoming and overdue grant reporting obligations within the given "
            "window. Already-submitted (done) obligations are excluded. Due dates are "
            "ISO strings. Cadence math is PROVISIONAL — verify each date against the "
            "real award letter before treating it as authoritative."
        ),
    )


# ---------------------------------------------------------------------------
# grant_status
# ---------------------------------------------------------------------------

def build_grant_status_tool(
    *,
    grants_config_path: str,
    submissions_path: str,
    owner_agent: str,
) -> ToolSpec:
    def handler(args: Mapping[str, Any]) -> dict[str, Any]:
        award_id = args.get("award_id", "")
        if not isinstance(award_id, str) or not award_id.strip():
            raise ToolArgError("award_id must be a non-empty string")
        award_id = award_id.strip()

        try:
            grants = load_grants(grants_config_path)
        except FileNotFoundError:
            return {"award_id": award_id, "obligations": [], "next_deadline": None}

        matching = [g for g in grants if g.award_id == award_id]
        if not matching:
            return {"award_id": award_id, "obligations": [], "next_deadline": None}

        store = SubmissionStore(submissions_path)
        submissions = store.all()

        # Use a wide window (look back 3 years, forward 3 years) to show all obligations
        obligations = compute_grant_schedule(
            matching,
            today=date.today(),
            lookback_days=3 * 365,
            horizon_days=3 * 365,
        )
        obligations = apply_submissions(obligations, submissions)

        next_deadline: str | None = None
        upcoming = [ob for ob in obligations if ob.status in ("upcoming", "overdue")]
        if upcoming:
            next_deadline = min(upcoming, key=lambda ob: ob.due_date).due_date.isoformat()

        return {
            "award_id": award_id,
            "obligations": [
                {
                    "report_label": ob.report_label,
                    "due_date": ob.due_date.isoformat(),
                    "status": ob.status,
                    "submitted_at": ob.submitted_at.isoformat() if ob.submitted_at else None,
                    "note": ob.note,
                }
                for ob in obligations
            ],
            "next_deadline": next_deadline,
        }

    return ToolSpec(
        name="grant_status",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "award_id": {
                    "type": "string",
                    "description": "The award_id of the grant to inspect (from list_grants).",
                },
            },
            "required": ["award_id"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Return all obligations for a specific grant award (including done), "
            "plus the next upcoming deadline. Use list_grants to discover award_ids."
        ),
    )


# ---------------------------------------------------------------------------
# list_grants
# ---------------------------------------------------------------------------

def build_list_grants_tool(
    *,
    grants_config_path: str,
    owner_agent: str,
) -> ToolSpec:
    def handler(args: Mapping[str, Any]) -> list[dict[str, Any]]:
        try:
            grants = load_grants(grants_config_path)
        except FileNotFoundError:
            return []

        return [
            {
                "award_id": g.award_id,
                "funder": g.funder,
                "title": g.title,
                "period_start": g.period_start.isoformat(),
                "period_end": g.period_end.isoformat(),
                "cadence": g.reporting_cadence,
            }
            for g in grants
        ]

    return ToolSpec(
        name="list_grants",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "List all tracked grants with their award_id, funder, title, period dates, "
            "and reporting cadence. Use award_id with grant_status or grant_deadlines "
            "for obligation detail."
        ),
    )


# ---------------------------------------------------------------------------
# grant_submit
# ---------------------------------------------------------------------------

def build_grant_submit_tool(
    *,
    submissions_path: str,
    owner_agent: str,
) -> ToolSpec:
    def handler(args: Mapping[str, Any]) -> dict[str, Any]:
        award_id = args.get("award_id", "")
        if not isinstance(award_id, str) or not award_id.strip():
            raise ToolArgError("award_id must be a non-empty string")
        award_id = award_id.strip()

        report_date_str = args.get("report_date", "")
        if not isinstance(report_date_str, str) or not report_date_str.strip():
            raise ToolArgError("report_date must be a non-empty ISO date string (YYYY-MM-DD)")
        report_date_str = report_date_str.strip()

        try:
            report_date = date.fromisoformat(report_date_str)
        except ValueError as exc:
            raise ToolArgError(
                f"report_date {report_date_str!r} is not a valid ISO date (YYYY-MM-DD): {exc}"
            ) from exc

        note = args.get("note", "")
        if not isinstance(note, str):
            note = str(note)

        store = SubmissionStore(submissions_path)
        store.record(award_id, report_date, note)

        return {
            "ok": True,
            "award_id": award_id,
            "report_date": report_date.isoformat(),
            "submitted_at": date.today().isoformat(),
        }

    return ToolSpec(
        name="grant_submit",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "award_id": {
                    "type": "string",
                    "description": "The award_id of the grant being reported on.",
                },
                "report_date": {
                    "type": "string",
                    "description": "ISO date string (YYYY-MM-DD) of the report due date being submitted.",
                },
                "note": {
                    "type": "string",
                    "description": "Optional submission note (e.g. portal reference, submitter).",
                },
            },
            "required": ["award_id", "report_date"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Record that a grant report has been submitted. The obligation will be "
            "marked 'done' and excluded from grant_deadlines going forward. "
            "This is the ONLY write operation in the steward tool surface — "
            "every invocation is audit-logged automatically."
        ),
    )


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------

def register_steward_tools(
    registry: Any,
    *,
    grants_config_path: str,
    submissions_path: str,
) -> None:
    """Register all four steward tools for aetheria and vett.

    Each tool is registered once per owner — 8 registrations total (4 tools × 2 owners).
    Scotty is intentionally excluded: grant-compliance is a research+oversight
    surface, not a bounded mechanical executor task.
    """
    for owner in _STEWARD_OWNERS:
        registry.register(build_grant_deadlines_tool(
            grants_config_path=grants_config_path,
            submissions_path=submissions_path,
            owner_agent=owner,
        ))
        registry.register(build_grant_status_tool(
            grants_config_path=grants_config_path,
            submissions_path=submissions_path,
            owner_agent=owner,
        ))
        registry.register(build_list_grants_tool(
            grants_config_path=grants_config_path,
            owner_agent=owner,
        ))
        registry.register(build_grant_submit_tool(
            submissions_path=submissions_path,
            owner_agent=owner,
        ))
