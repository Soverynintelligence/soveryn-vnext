"""Aetheria objective_assign / objective_status tools."""
from __future__ import annotations

from pathlib import Path

import pytest

from soveryn.citizens.registry import Citizen, connect, register
from soveryn.platform.objective_tools import register_objective_tools
from soveryn.platform.tools.registry import ToolRegistry


@pytest.fixture
def tool_db(tmp_path: Path, monkeypatch):
    db = tmp_path / "citizens.db"
    monkeypatch.setenv("SOVERYN_CITIZENS_DB", str(db))
    with connect(db) as conn:
        for cid, name in (("aetheria", "Aetheria"), ("vett", "V.E.T.T.")):
            register(
                conn,
                Citizen(
                    id=cid,
                    display_name=name,
                    workspace_path=str(tmp_path / "desks" / cid),
                ),
            )
    return db


def test_objective_assign_and_status(tool_db):
    reg = ToolRegistry()
    register_objective_tools(reg, owner_agent="aetheria")
    out = reg.invoke(
        "aetheria",
        "objective_assign",
        {
            "desk": "cwg",
            "title": "Test pricing dig",
            "brief": "Find three sourced prices.",
            "owner_id": "vett",
            "success_criteria": "3 rows",
            "enqueue": True,
        },
    )
    assert out.get("ok") is True
    assert out.get("objective_id")
    assert out.get("commission_id")
    st = reg.invoke(
        "aetheria",
        "objective_status",
        {"objective_id": out["objective_id"]},
    )
    assert st.get("ok") is True
    assert st["objective"]["state"] == "active"
    listed = reg.invoke("aetheria", "objective_status", {"desk": "cwg"})
    assert listed.get("count", 0) >= 1


def test_objective_verify_closes_loop(tool_db):
    reg = ToolRegistry()
    register_objective_tools(reg, owner_agent="aetheria")
    out = reg.invoke(
        "aetheria",
        "objective_assign",
        {
            "desk": "soveryn",
            "title": "Smoke verify loop",
            "brief": "Tiny standing job for the verify tool.",
            "owner_id": "vett",
            "enqueue": False,
        },
    )
    oid = out["objective_id"]
    # Simulate execute finishing → ready_for_verify
    from soveryn.citizens import objectives as objectives_mod
    from soveryn.citizens.registry import connect

    with connect(tool_db) as conn:
        objectives_mod.set_state(
            conn, oid, state="ready_for_verify", at="2026-08-22T22:00:00Z"
        )
    waiting = reg.invoke(
        "aetheria",
        "objective_status",
        {"state": "ready_for_verify"},
    )
    assert waiting.get("ok") is True
    assert any(o["id"] == oid for o in waiting.get("objectives") or [])

    closed = reg.invoke(
        "aetheria",
        "objective_verify",
        {
            "objective_id": oid,
            "state": "done",
            "note": "Jon accepted the brief.",
        },
    )
    assert closed.get("ok") is True
    assert closed.get("state") == "done"
    assert closed.get("prior_state") == "ready_for_verify"
    st = reg.invoke("aetheria", "objective_status", {"objective_id": oid})
    assert st["objective"]["state"] == "done"
    path = Path(st["objective"]["checkpoint_path"])
    assert (path / "verify.md").is_file()
    ck = st.get("checkpoint") or {}
    assert "Jon accepted" in (ck.get("verify_note") or "")
