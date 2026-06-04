"""recent_self_audit tool factory.

Queries three audit tables (coord_event_log + coord_references + nodes
filtered to library writes by the agent), unifies the results into a
chronological timeline, and returns them. Owner-keyed so each agent
only sees its own actions.

Honest about coverage: not all tools emit audit events. The schema
description and the tool's return payload both surface what IS and
ISN'T covered so the agent doesn't assume absence of audit means
absence of action.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from soveryn.platform.tools.registry import ToolArgError, ToolRegistry, ToolSpec


DEFAULT_WINDOW_MINUTES = 60
MAX_WINDOW_MINUTES = 60 * 24      # one day
MAX_RECORDS = 200

AUDIT_COVERAGE_NOTE = (
    "Coverage: this tool returns actions from the COORD board event log, "
    "COORD read references, and LIBRARY writes — every action you take "
    "via your coordination tools and your library write tool is captured "
    "here. NOT covered: lattice searches (search_lattice_by_*), file reads "
    "(read_file / list_directory), library searches (search_library). "
    "Those tools don't emit audit events. If you don't see an action you "
    "took here, it may still have happened via an uncovered tool — defer "
    "to this audit log only for what's in scope, and acknowledge uncertainty "
    "for anything outside it."
)


def build_recent_self_audit_tool(
    *,
    lattice_db_path: Path,
    owner_agent: str,
) -> ToolSpec:
    """Tool factory. Reads three audit tables in the lattice DB and unifies
    into a chronological timeline scoped to this agent."""

    def handler(args: Mapping[str, Any]) -> Any:
        window_arg = args.get("window_minutes", DEFAULT_WINDOW_MINUTES)
        if not isinstance(window_arg, int) or window_arg <= 0:
            raise ToolArgError("window_minutes must be a positive integer")
        if window_arg > MAX_WINDOW_MINUTES:
            raise ToolArgError(
                f"window_minutes must be <= {MAX_WINDOW_MINUTES} (one day)"
            )
        now = datetime.now()
        since = (now - timedelta(minutes=window_arg)).isoformat()
        actions: list[dict[str, Any]] = []

        with sqlite3.connect(str(lattice_db_path)) as con:
            con.row_factory = sqlite3.Row
            # ─ coord_event_log: create / status / promote / archive / block_added ─
            for r in con.execute(
                "SELECT id, kind, node_id, chain_depth, parent_event_id, "
                "payload_json, created_at "
                "FROM coord_event_log "
                "WHERE actor_agent = ? AND created_at >= ? "
                "ORDER BY created_at DESC",
                (owner_agent, since),
            ).fetchall():
                payload = {}
                try:
                    payload = json.loads(r["payload_json"] or "{}")
                except (json.JSONDecodeError, TypeError):
                    pass
                actions.append({
                    "kind": f"coord.{r['kind']}",
                    "timestamp": r["created_at"],
                    "node_id": r["node_id"],
                    "chain_depth": r["chain_depth"],
                    "parent_event_id": r["parent_event_id"],
                    "details": payload,
                })
            # ─ coord_references: read calls ─
            # Group by created_at to one record per read (each read can log
            # multiple referenced nodes; we collapse them).
            for r in con.execute(
                "SELECT created_at, "
                "       GROUP_CONCAT(referenced_node_id) AS refs, "
                "       COUNT(*) AS ref_count "
                "FROM coord_references "
                "WHERE source_agent = ? AND created_at >= ? "
                "GROUP BY created_at "
                "ORDER BY created_at DESC",
                (owner_agent, since),
            ).fetchall():
                actions.append({
                    "kind": "coord.read",
                    "timestamp": r["created_at"],
                    "node_id": None,
                    "details": {
                        "ref_count": r["ref_count"],
                        "referenced_node_ids": (r["refs"] or "").split(",") if r["refs"] else [],
                    },
                })
            # ─ library writes from the nodes table ─
            for r in con.execute(
                "SELECT id, content, created_at, tags "
                "FROM nodes "
                "WHERE agent = ? AND layer = 'library' AND created_at >= ? "
                "ORDER BY created_at DESC",
                (owner_agent, since),
            ).fetchall():
                tags = []
                try:
                    tags = json.loads(r["tags"] or "[]")
                except (json.JSONDecodeError, TypeError):
                    pass
                actions.append({
                    "kind": "library.write",
                    "timestamp": r["created_at"],
                    "node_id": r["id"],
                    "details": {
                        "content_head": (r["content"] or "")[:200],
                        "tags": tags,
                    },
                })

        # Sort unified timeline most-recent first; cap at MAX_RECORDS.
        actions.sort(key=lambda a: a["timestamp"], reverse=True)
        truncated = len(actions) > MAX_RECORDS
        if truncated:
            actions = actions[:MAX_RECORDS]
        return {
            "agent": owner_agent,
            "window_minutes": window_arg,
            "queried_at": now.isoformat(),
            "since": since,
            "count": len(actions),
            "truncated": truncated,
            "actions": actions,
            "audit_coverage_note": AUDIT_COVERAGE_NOTE,
        }

    return ToolSpec(
        name="recent_self_audit",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "window_minutes": {
                    "type": "integer",
                    "description": (
                        f"How far back to look, in minutes. Default "
                        f"{DEFAULT_WINDOW_MINUTES}, max {MAX_WINDOW_MINUTES} "
                        f"(one day). The audit log doesn't carry conversation "
                        f"context, only the actions themselves."
                    ),
                },
            },
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Return your own recent actions from the audit log. Use this "
            "when you need to verify whether you actually did something "
            "(called a tool, posted to boards, wrote to the library) "
            "rather than relying on your conversation history — which does "
            "NOT include intermediate tool calls and can lead you to deny "
            "actions you actually took. The audit log is ground truth; "
            "defer to it over self-recall.\n\n"
            "Coverage: covers coord board operations (create/update/"
            "promote/archive/block/read) and library writes. Does NOT "
            "cover lattice searches, file reads, or library searches "
            "(those tools don't emit audit events). The returned payload "
            "includes a coverage note as a reminder."
        ),
    )


def register_audit_tools(
    registry: ToolRegistry,
    *,
    lattice_db_path: Path,
    owner_agent: str,
) -> None:
    registry.register(build_recent_self_audit_tool(
        lattice_db_path=lattice_db_path, owner_agent=owner_agent,
    ))
