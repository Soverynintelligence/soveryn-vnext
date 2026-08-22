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
