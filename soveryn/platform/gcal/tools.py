"""Eve tools: calendar status + list (read) + create (Gate-only)."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from soveryn.platform.gcal.client import (
    complete_event,
    create_event,
    gcal_status,
    list_events,
)
from soveryn.platform.tools.registry import ToolArgError, ToolRegistry, ToolSpec


def build_eve_calendar_status_tool(*, owner_agent: str = "eve") -> ToolSpec:
    def handler(_args: Mapping[str, Any]) -> Any:
        return gcal_status()

    return ToolSpec(
        name="eve_calendar_status",
        owner=owner_agent,
        schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=handler,
        description=(
            "Read-only: is CWG Google Calendar OAuth configured and authorized? "
            "Does not create events."
        ),
    )


def build_eve_calendar_list_tool(*, owner_agent: str = "eve") -> ToolSpec:
    def handler(args: Mapping[str, Any]) -> Any:
        days = args.get("days", 7)
        if not isinstance(days, int) or isinstance(days, bool) or days <= 0:
            raise ToolArgError("days must be a positive integer")
        days_back = args.get("days_back", 7)
        if not isinstance(days_back, int) or isinstance(days_back, bool) or days_back < 0:
            raise ToolArgError("days_back must be an integer >= 0")
        query = args.get("query") or ""
        if query is not None and not isinstance(query, str):
            raise ToolArgError("query must be a string")
        return list_events(
            days=days, days_back=days_back, query=str(query or "")
        )

    return ToolSpec(
        name="eve_calendar_list",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 31,
                    "default": 7,
                    "description": "How many days ahead to list (1–31). Default 7.",
                },
                "days_back": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 31,
                    "default": 7,
                    "description": "How many days back to include (done jobs). Default 7.",
                },
                "query": {
                    "type": "string",
                    "description": "Optional text filter (job name, person, site).",
                },
            },
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "List CWG Google Calendar jobs (default: last 7 days + next 7). "
            "Each event has cwg_status open|done. Read-only. "
            "If needs_login, tell Jon to run "
            "`python -m soveryn.platform.gcal authorize`."
        ),
    )


def build_eve_calendar_create_tool(
    *,
    owner_agent: str = "eve",
    create_fn=None,
) -> ToolSpec:
    creator = create_fn or create_event

    def handler(args: Mapping[str, Any]) -> Any:
        summary = args.get("summary", "")
        start = args.get("start", "")
        if not isinstance(summary, str) or not summary.strip():
            raise ToolArgError("summary must be a non-empty string")
        if not isinstance(start, str) or not start.strip():
            raise ToolArgError("start must be an ISO-8601 datetime")
        end = args.get("end") or ""
        location = args.get("location") or ""
        description = args.get("description") or ""
        for name, val in (
            ("end", end),
            ("location", location),
            ("description", description),
        ):
            if val is not None and not isinstance(val, str):
                raise ToolArgError(f"{name} must be a string")
        return creator(
            summary=summary.strip(),
            start=start.strip(),
            end=str(end or "").strip(),
            location=str(location or "").strip(),
            description=str(description or "").strip(),
        )

    return ToolSpec(
        name="eve_calendar_create",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Event title, e.g. 'CWG — pond clean, Pinehurst'.",
                },
                "start": {
                    "type": "string",
                    "description": "ISO-8601 start, e.g. 2026-09-08T10:00 (America/New_York if no tz).",
                },
                "end": {
                    "type": "string",
                    "description": "ISO-8601 end. Default start + 1 hour.",
                },
                "location": {"type": "string", "description": "Optional place."},
                "description": {"type": "string", "description": "Optional notes."},
            },
            "required": ["summary", "start"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Create one event on the CWG Google Calendar. Messages Gate Allow "
            "required — never cadence. If needs_login, stop and tell Jon."
        ),
    )


def build_eve_calendar_complete_tool(
    *,
    owner_agent: str = "eve",
    complete_fn=None,
) -> ToolSpec:
    completer = complete_fn or complete_event

    def handler(args: Mapping[str, Any]) -> Any:
        eid = args.get("event_id", "")
        if not isinstance(eid, str) or not eid.strip():
            raise ToolArgError("event_id must be a non-empty string from eve_calendar_list")
        return completer(event_id=eid.strip())

    return ToolSpec(
        name="eve_calendar_complete",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "Event id from eve_calendar_list.",
                }
            },
            "required": ["event_id"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Mark a CWG calendar job done (does not delete it). "
            "Messages Gate Allow required — never cadence."
        ),
    )


def register_gcal_tools(registry: ToolRegistry, *, owner_agent: str = "eve") -> None:
    registry.register(build_eve_calendar_status_tool(owner_agent=owner_agent))
    registry.register(build_eve_calendar_list_tool(owner_agent=owner_agent))
    registry.register(build_eve_calendar_create_tool(owner_agent=owner_agent))
    registry.register(build_eve_calendar_complete_tool(owner_agent=owner_agent))
