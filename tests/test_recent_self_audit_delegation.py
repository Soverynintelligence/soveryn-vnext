"""An agent must be able to see the tasks it dispatched.

2026-07-27: Aetheria dispatched the Cross-Rail task to Scotty twice. Both
dispatches are in delegation.db. She then ran recent_self_audit, saw no
dispatch, and concluded she had HALLUCINATED the action — confessing to a
fabrication she had not committed.

The audit tool read three lattice tables; dispatch_task writes to a separate
database and emits no audit event. The dispatch was invisible by construction.

The coverage note already warned that uncovered tools exist and to "acknowledge
uncertainty". She read it and concluded fabrication anyway — a caveat in prose
did not hold. Hence a test, not a better warning.
"""
import sqlite3
from pathlib import Path

from soveryn.platform.audit.tools import build_recent_self_audit_tool


def _delegation_db(tmp_path: Path) -> Path:
    p = tmp_path / "delegation.db"
    con = sqlite3.connect(p)
    con.execute(
        "CREATE TABLE delegation_tasks (id TEXT, dispatched_by TEXT, objective TEXT,"
        " scope TEXT, acceptance TEXT, status TEXT, worktree_path TEXT, branch TEXT,"
        " diff TEXT, test_output TEXT, summary TEXT, review_feedback TEXT,"
        " created_at TEXT, updated_at TEXT)"
    )
    con.execute(
        "INSERT INTO delegation_tasks (id, dispatched_by, objective, scope, acceptance,"
        " status, summary, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
        ("task-1", "aetheria", "Implement the thing", "soveryn/context/",
         "pytest tests/test_thing.py", "failed", "execution raised before acceptance",
         "2999-01-01T00:00:00", "2999-01-01T00:05:00"),
    )
    con.commit()
    con.close()
    return p


def _lattice_db(tmp_path: Path) -> Path:
    p = tmp_path / "lattice.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE coord_event_log (id TEXT, kind TEXT, node_id TEXT,"
                " chain_depth INT, parent_event_id TEXT, payload_json TEXT,"
                " actor_agent TEXT, created_at TEXT)")
    con.execute("CREATE TABLE coord_references (source_agent TEXT,"
                " referenced_node_id TEXT, created_at TEXT)")
    con.execute("CREATE TABLE nodes (id TEXT, content TEXT, created_at TEXT,"
                " tags TEXT, agent TEXT, layer TEXT)")
    con.commit()
    con.close()
    return p


def test_dispatched_tasks_appear_in_self_audit(tmp_path):
    """The exact gap that made her confess to a fabrication she didn't commit."""
    tool = build_recent_self_audit_tool(
        lattice_db_path=_lattice_db(tmp_path),
        owner_agent="aetheria",
        delegation_db_path=_delegation_db(tmp_path),
    )
    res = tool.handler({"window_minutes": 1440})
    kinds = [a["kind"] for a in res["actions"]]
    assert any(k.startswith("delegation.") for k in kinds), (
        "recent_self_audit does not surface delegation dispatches. An agent that "
        "cannot see a task it dispatched may conclude it fabricated the dispatch."
    )


def test_delegation_entry_carries_status_and_objective(tmp_path):
    tool = build_recent_self_audit_tool(
        lattice_db_path=_lattice_db(tmp_path),
        owner_agent="aetheria",
        delegation_db_path=_delegation_db(tmp_path),
    )
    entry = next(a for a in tool.handler({"window_minutes": 1440})["actions"]
                 if a["kind"].startswith("delegation."))
    assert entry["kind"] == "delegation.failed"
    assert "Implement the thing" in entry["details"]["objective_head"]
    assert entry["details"]["summary"] == "execution raised before acceptance"


def test_missing_delegation_db_does_not_break_the_audit(tmp_path):
    """A dead delegation DB must degrade, not take the whole audit down."""
    tool = build_recent_self_audit_tool(
        lattice_db_path=_lattice_db(tmp_path),
        owner_agent="aetheria",
        delegation_db_path=tmp_path / "does-not-exist.db",
    )
    assert tool.handler({"window_minutes": 60})["count"] == 0


def test_coverage_note_claims_delegation_coverage():
    """The note is shown to her verbatim; it must not under-claim what she can see."""
    from soveryn.platform.audit.tools import AUDIT_COVERAGE_NOTE
    assert "DELEGATION" in AUDIT_COVERAGE_NOTE, (
        "The coverage note must tell her delegations are visible, or she will "
        "keep discounting what the audit shows."
    )
