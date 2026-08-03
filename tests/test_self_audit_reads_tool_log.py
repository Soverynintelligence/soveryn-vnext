"""`recent_self_audit` must read the tool-invocation log.

This is the 2026-07-27 incident, root-caused on 2026-08-03.

Aetheria dispatched a task, reported it accurately with its id, then queried
`recent_self_audit`, received an empty result, and concluded she had fabricated
the work. She apologised twice, four hours apart, for work she had genuinely
done — the subject of 10.5281/zenodo.21650072 and 10.5281/zenodo.21712932.

The record existed the entire time:

    2026-07-27T21:20:58   aetheria/dispatch_task   ok=True

`ToolRegistry` has logged every mediated call through its default audit hook
since 2026-05-31 — 17,436 rows when this test was written. `recent_self_audit`
queried the coordination event log, coordination references, library writes and
delegation tasks, and never the tool log. The evidence was on disk, in a store
the self-audit tool did not open.

So the incident was not a model failing to know itself. It was an instrument
pointed away from the record. That is worth a permanent test.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from soveryn.platform.audit.tools import (
    AUDIT_COVERAGE_NOTE,
    TOOL_AUDIT_SOURCE,
    build_recent_self_audit_tool,
)


@pytest.fixture()
def telemetry_db(tmp_path):
    """A telemetry store shaped like the real one, holding one dispatch."""
    path = tmp_path / "telemetry.db"
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE telemetry (id INTEGER PRIMARY KEY, source TEXT, "
        "event_type TEXT, level TEXT, payload TEXT, created_at TEXT)"
    )
    from datetime import datetime
    now = datetime.now().isoformat()
    con.execute(
        "INSERT INTO telemetry (source, event_type, level, payload, created_at) "
        "VALUES (?,?,?,?,?)",
        (TOOL_AUDIT_SOURCE, "tool.invoked", "info",
         json.dumps({"agent": "aetheria", "tool_name": "dispatch_task",
                     "ok": True, "error": None}), now),
    )
    # A different agent's call, to prove owner scoping.
    con.execute(
        "INSERT INTO telemetry (source, event_type, level, payload, created_at) "
        "VALUES (?,?,?,?,?)",
        (TOOL_AUDIT_SOURCE, "tool.invoked", "info",
         json.dumps({"agent": "vett", "tool_name": "web_search",
                     "ok": True, "error": None}), now),
    )
    con.commit()
    con.close()
    return path


@pytest.fixture()
def empty_lattice(tmp_path):
    path = tmp_path / "lattice.db"
    con = sqlite3.connect(path)
    # Schemas copied from the live lattice, not invented — an invented schema
    # is how this test first failed.
    con.execute("CREATE TABLE nodes (id TEXT PRIMARY KEY, type TEXT, layer TEXT, "
                "agent TEXT, content TEXT, intensity REAL, salience REAL, "
                "access_count INT, tags TEXT, created_at TEXT, updated_at TEXT, "
                "embedding BLOB, intent TEXT, provenance TEXT)")
    con.execute("CREATE TABLE coord_event_log (id TEXT PRIMARY KEY, kind TEXT, "
                "node_id TEXT, actor_agent TEXT, chain_depth INTEGER DEFAULT 0, "
                "parent_event_id TEXT, payload_json TEXT, created_at TEXT)")
    con.execute("CREATE TABLE coord_references (id TEXT PRIMARY KEY, "
                "source_node_id TEXT, referenced_node_id TEXT, "
                "source_agent TEXT, created_at TEXT)")
    con.commit(); con.close()
    return path


def _audit(lattice, telemetry, agent="aetheria"):
    spec = build_recent_self_audit_tool(
        lattice_db_path=lattice, owner_agent=agent, telemetry_db_path=telemetry,
    )
    return spec.handler({"window_minutes": 60})


def test_dispatch_is_visible_in_the_audit(empty_lattice, telemetry_db):
    """The exact query that returned empty on 2026-07-27."""
    out = _audit(empty_lattice, telemetry_db)
    kinds = [a["kind"] for a in out["actions"]]
    assert "tool.dispatch_task" in kinds, (
        "recent_self_audit cannot see a dispatch that IS in the tool log — "
        "this is the false-confession failure, restored"
    )


def test_audit_is_owner_scoped(empty_lattice, telemetry_db):
    """Vett's calls must not appear in Aetheria's self-audit."""
    out = _audit(empty_lattice, telemetry_db)
    assert not [a for a in out["actions"] if a["kind"] == "tool.web_search"]


def test_other_agent_sees_only_their_own(empty_lattice, telemetry_db):
    out = _audit(empty_lattice, telemetry_db, agent="vett")
    kinds = [a["kind"] for a in out["actions"]]
    assert "tool.web_search" in kinds
    assert "tool.dispatch_task" not in kinds


def test_unreadable_log_is_reported_not_silently_empty(empty_lattice, tmp_path):
    """A missing telemetry store must surface, not read as 'no actions'.

    Silence is what caused the incident. If the source cannot be read, the
    agent has to be told, or absence looks like evidence again.
    """
    out = _audit(empty_lattice, tmp_path / "does-not-exist.db")
    kinds = [a["kind"] for a in out["actions"]]
    assert "audit.source_unavailable" in kinds or out["count"] == 0
    if "audit.source_unavailable" in kinds:
        entry = next(a for a in out["actions"] if a["kind"] == "audit.source_unavailable")
        assert "NOT evidence" in entry["details"]["note"]


def test_coverage_note_does_not_claim_tools_are_uncovered():
    """The note is what the agent calibrates on; a stale one misleads.

    It previously said file reads and searches emitted no audit events. They
    do — every registry-mediated call does. An agent reading that would
    discount evidence it actually holds.
    """
    lowered = AUDIT_COVERAGE_NOTE.lower()
    assert "don't emit audit events" not in lowered
    assert "every tool call" in lowered
    assert "absence" in lowered, "the note must still say what absence means"
