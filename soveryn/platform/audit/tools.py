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

#: telemetry `source` written by ToolRegistry's default audit hook.
TOOL_AUDIT_SOURCE = "platform.tools.registry"
from typing import Any

from soveryn.platform.tools.registry import ToolArgError, ToolRegistry, ToolSpec


DEFAULT_WINDOW_MINUTES = 60
MAX_WINDOW_MINUTES = 60 * 24      # one day
MAX_RECORDS = 200

AUDIT_COVERAGE_NOTE = (
    "Coverage: EVERY tool call you make through the registry is recorded — "
    "including searches, file reads and directory listings — plus the COORD "
    "board event log, COORD read references, LIBRARY writes, and DELEGATION "
    "dispatches with their status. "
    "NOT covered: anything you did outside a tool call (reasoning, text you "
    "wrote, decisions you narrated), and any window before 2026-05-31 when "
    "tool auditing began. "
    "If this returns 'audit.source_unavailable', the log could not be read "
    "this query and an empty result means NOTHING — not that you took no "
    "actions. Absence of a record is evidence only when the source was "
    "readable and in scope."
)


def build_recent_self_audit_tool(
    *,
    lattice_db_path: Path,
    owner_agent: str,
    delegation_db_path: Path | None = None,
    telemetry_db_path: Path | None = None,
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

        # ─ delegation dispatches ─
        # Lives in its own DB, so it needs its own connection. Without this an
        # agent cannot see tasks it dispatched, and may wrongly conclude it
        # fabricated the dispatch (2026-07-27).
        if delegation_db_path is not None and Path(delegation_db_path).is_file():
            try:
                with sqlite3.connect(str(delegation_db_path)) as dcon:
                    dcon.row_factory = sqlite3.Row
                    for r in dcon.execute(
                        "SELECT id, objective, scope, acceptance, status, summary, "
                        "       created_at, updated_at "
                        "FROM delegation_tasks "
                        "WHERE dispatched_by = ? AND created_at >= ? "
                        "ORDER BY created_at DESC",
                        (owner_agent, since),
                    ).fetchall():
                        actions.append({
                            "kind": f"delegation.{r['status']}",
                            "timestamp": r["created_at"],
                            "node_id": r["id"],
                            "details": {
                                "objective_head": (r["objective"] or "")[:200],
                                "scope": r["scope"],
                                "acceptance": r["acceptance"],
                                "status": r["status"],
                                "summary": r["summary"],
                                "updated_at": r["updated_at"],
                            },
                        })
            except sqlite3.Error:
                # Never let an unreadable delegation DB break the audit.
                pass

        # ── tool-invocation audit ────────────────────────────────────────
        # The registry has logged every mediated tool call since 2026-05-31 via
        # its default audit hook — 17,436 rows at the time this was added. This
        # tool never read them.
        #
        # That is the 2026-07-27 incident. Aetheria dispatched a task, reported
        # it with its id, then queried recent_self_audit, got nothing, and
        # concluded she had fabricated the work. The record existed:
        #
        #   2026-07-27T21:20:58  aetheria/dispatch_task  ok=True
        #
        # It sat in telemetry, written by the audit hook nineteen minutes after
        # she reported the dispatch, in a store this tool did not query. Two
        # papers were written about the confession; the evidence was on disk the
        # whole time. See 10.5281/zenodo.21650072.
        if telemetry_db_path is not None:
            try:
                with sqlite3.connect(
                    f"file:{telemetry_db_path}?mode=ro", uri=True
                ) as tcon:
                    tcon.row_factory = sqlite3.Row
                    for r in tcon.execute(
                        "SELECT created_at, payload FROM telemetry "
                        "WHERE source = ? AND created_at >= ? "
                        "ORDER BY created_at DESC LIMIT 200",
                        (TOOL_AUDIT_SOURCE, since),
                    ).fetchall():
                        try:
                            payload = json.loads(r["payload"])
                        except (TypeError, ValueError):
                            continue
                        if payload.get("agent") != owner_agent:
                            continue
                        actions.append({
                            "kind": f"tool.{payload.get('tool_name', 'unknown')}",
                            "timestamp": r["created_at"],
                            "node_id": None,
                            "details": {
                                "tool": payload.get("tool_name"),
                                "ok": payload.get("ok"),
                                "error": payload.get("error"),
                            },
                        })
            except sqlite3.Error:
                # An unreadable telemetry store must not break the audit — but
                # it MUST be visible, or absence reads as "no tool calls".
                actions.append({
                    "kind": "audit.source_unavailable",
                    "timestamp": now.isoformat(),
                    "node_id": None,
                    "details": {
                        "source": "tool_audit",
                        "note": "tool-invocation log unreadable this query; "
                                "absence of tool calls below is NOT evidence "
                                "that none occurred",
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
    delegation_db_path: Path | None = None,
    telemetry_db_path: Path | None = None,
) -> None:
    registry.register(build_recent_self_audit_tool(
        lattice_db_path=lattice_db_path, owner_agent=owner_agent,
        delegation_db_path=delegation_db_path,
        telemetry_db_path=telemetry_db_path,
    ))
