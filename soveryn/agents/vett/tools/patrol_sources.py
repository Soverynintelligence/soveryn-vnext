"""Vett-only patrol tools: read_patrol_sources + mark_source_visited.

read_patrol_sources merges the static YAML with per-source state from
vett_patrol_state so Vett sees everything he needs in one call. He uses
this at the start of a patrol to plan which sources actually need a
visit (vs. which were just checked).

mark_source_visited is the bookkeeping primitive — Vett calls this after
a successful fetch so the next patrol's read_patrol_sources reflects the
visit. We could auto-bookkeep on fetch_url, but the explicit-call
pattern keeps the audit trail clean and gives Vett the choice to
"checked but found nothing worth a Signal" without surfacing a misleading
fetch in his timeline.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from soveryn.agents.vett.patrol.source_list import (
    PATROL_SOURCES_DEFAULT_PATH,
    PatrolSourceError,
    SourceList,
    load_source_list,
    mark_source_visited as _mark_source_visited_state,
    read_patrol_state,
)
from soveryn.platform.tools.registry import ToolArgError, ToolRegistry, ToolSpec


def build_read_patrol_sources_tool(
    *,
    lattice_db_path: Path,
    sources_yaml_path: Path = PATROL_SOURCES_DEFAULT_PATH,
    owner_agent: str = "vett",
) -> ToolSpec:
    """Return Vett's patrol list merged with per-source dynamic state."""

    def handler(args: Mapping[str, Any]) -> Any:
        # No args — keep the surface tight.
        try:
            source_list = load_source_list(sources_yaml_path)
        except PatrolSourceError as e:
            return {"error": "source_list_invalid", "message": str(e), "sources": []}
        urls = [s.url for s in source_list.sources]
        state_map = read_patrol_state(lattice_db_path, urls=urls)
        now = datetime.now()
        out = []
        for s in source_list.sources:
            st = state_map[s.url]
            due = _is_due_for_visit(s.visit_every_hours, st.last_visited_at, now)
            hours_since = None
            if st.last_visited_at is not None:
                hours_since = round(
                    (now - st.last_visited_at).total_seconds() / 3600, 1
                )
            out.append({
                "url": s.url,
                "kind": s.kind,
                "domain": s.domain,
                "visit_every_hours": s.visit_every_hours,
                "keywords": list(s.keywords),
                "last_visited_at": (
                    st.last_visited_at.isoformat() if st.last_visited_at else None
                ),
                "hours_since_last_visit": hours_since,
                "due_for_visit": due,
                "last_error_at": (
                    st.last_error_at.isoformat() if st.last_error_at else None
                ),
                "last_error": st.last_error,
                "visit_count": st.visit_count,
            })
        return {
            "source_count": len(out),
            "due_count": sum(1 for x in out if x["due_for_visit"]),
            "sources": out,
        }

    return ToolSpec(
        name="read_patrol_sources",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Read Vett's patrol source list merged with per-source dynamic "
            "state (last_visited_at, last_error, visit_count). Each entry "
            "carries `due_for_visit` so the patrol can prioritize sources "
            "that haven't been checked recently. Sources never visited are "
            "always due."
        ),
    )


def build_mark_source_visited_tool(
    *,
    lattice_db_path: Path,
    owner_agent: str = "vett",
) -> ToolSpec:
    """Record that Vett visited a source. URL must match a YAML-listed source.

    The handler is forgiving — passing a URL that ISN'T in the YAML still
    writes a state row (since the table only constrains by URL). Vett's
    prompt encourages him to use URLs from the source list, but if he
    fetches a redirect-resolved URL we shouldn't reject — the dynamic
    state still tells the right story.
    """

    def handler(args: Mapping[str, Any]) -> Any:
        url = args.get("url", "")
        if not isinstance(url, str) or not url.strip():
            raise ToolArgError("url must be a non-empty string")
        url = url.strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            raise ToolArgError(f"url must be http(s); got {url!r}")
        _mark_source_visited_state(lattice_db_path, url)
        return {"url": url, "marked": True, "marked_at": datetime.now().isoformat()}

    return ToolSpec(
        name="mark_source_visited",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": (
                        "The source URL Vett just visited. Bumps visit_count "
                        "and clears any prior error state."
                    ),
                },
            },
            "required": ["url"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Record a successful visit to a patrol source so future patrols "
            "see updated last_visited_at. Call this after a `fetch_url` for "
            "a source on your patrol list."
        ),
    )


def register_vett_patrol_tools(
    registry: ToolRegistry,
    *,
    lattice_db_path: Path,
    sources_yaml_path: Path = PATROL_SOURCES_DEFAULT_PATH,
) -> None:
    """Register Vett's two patrol tools."""
    registry.register(build_read_patrol_sources_tool(
        lattice_db_path=lattice_db_path,
        sources_yaml_path=sources_yaml_path,
    ))
    registry.register(build_mark_source_visited_tool(
        lattice_db_path=lattice_db_path,
    ))


def _is_due_for_visit(
    visit_every_hours: int,
    last_visited_at: datetime | None,
    now: datetime,
) -> bool:
    if last_visited_at is None:
        return True
    elapsed_hours = (now - last_visited_at).total_seconds() / 3600
    return elapsed_hours >= visit_every_hours
