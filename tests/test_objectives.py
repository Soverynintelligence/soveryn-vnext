"""Standing objectives + research marker parsing."""
from __future__ import annotations

from pathlib import Path

import pytest

from soveryn.citizens import objectives as objectives_mod
from soveryn.citizens.registry import Citizen, connect, register
from soveryn.citizens.research_runner import parse_objective_id, _extract_table_rows


@pytest.fixture
def obj_db(tmp_path: Path):
    db = tmp_path / "citizens.db"
    with connect(db) as conn:
        register(
            conn,
            Citizen(
                id="vett",
                display_name="V.E.T.T.",
                workspace_path=str(tmp_path / "desks" / "vett"),
            ),
        )
        register(
            conn,
            Citizen(
                id="aetheria",
                display_name="Aetheria",
                workspace_path=str(tmp_path / "desks" / "aetheria"),
            ),
        )
    return db, tmp_path


def test_assign_objective_creates_checkpoint(obj_db):
    db, tmp = obj_db
    with connect(db) as conn:
        row = objectives_mod.assign(
            conn,
            desk="cwg",
            title="Fountain maintenance pricing",
            brief="Pull sourced prices across platforms.",
            at="2026-08-22T18:00:00Z",
            owner_id="vett",
            success_criteria="table with >=3 sourced prices",
            assigned_by="jon",
        )
    assert row["desk"] == "cwg"
    assert row["state"] == "active"
    path = Path(row["checkpoint_path"])
    assert (path / "brief.md").is_file()
    assert (path / "checkpoint.json").is_file()
    body = objectives_mod.research_commission_body(row)
    assert parse_objective_id(body) == row["id"]


def test_extract_table_rows():
    text = """
| Brand | Model | Coverage | Price | Source |
|---|---|---|---|---|
| Aquascape | BioFalls 1000 | 1000 gal | ~$207 | ThePondOutlet |
| Oase | Foo | bar | $99 | example.com |
"""
    rows = _extract_table_rows(text)
    assert len(rows) >= 2
    assert rows[0]["brand"] == "Aquascape"
    assert "$207" in rows[0]["price"]
