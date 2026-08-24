"""Standing autonomy seeds — desks keep open work without Jon poking."""
from __future__ import annotations

from pathlib import Path

import pytest

from soveryn.citizens import objectives as objectives_mod
from soveryn.citizens.registry import Citizen, connect, register
from soveryn.citizens.standing_work import ensure_standing_objectives


@pytest.fixture()
def db(tmp_path: Path):
    path = tmp_path / "citizens.db"
    with connect(path) as conn:
        for cid, name in (
            ("aetheria", "Aetheria"),
            ("vett", "V.E.T.T."),
            ("scotty", "Scotty"),
            ("eve", "Eve"),
            ("kernel", "Kernel"),
        ):
            register(
                conn,
                Citizen(
                    id=cid,
                    display_name=name,
                    workspace_path=str(tmp_path / cid),
                ),
            )
        yield conn


def test_ensure_standing_creates_soveryn_and_cwg(db):
    created = ensure_standing_objectives(db)
    assert len(created) == 2
    desks = {r["desk"] for r in created}
    assert desks == {"soveryn", "cwg"}
    # Idempotent
    assert ensure_standing_objectives(db) == []
    open_s = objectives_mod.list_objectives(db, desk="soveryn", state="active")
    open_c = objectives_mod.list_objectives(db, desk="cwg", state="active")
    assert len(open_s) == 1
    assert len(open_c) == 1
    assert open_s[0]["owner_id"] == "kernel"
    assert open_c[0]["owner_id"] == "vett"


def test_build_vs_research_commission_body():
    build = objectives_mod.commission_body_for(
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "desk": "soveryn",
            "owner_id": "kernel",
            "title": "t",
            "brief": "b",
            "success_criteria": "s",
        }
    )
    research = objectives_mod.commission_body_for(
        {
            "id": "00000000-0000-0000-0000-000000000002",
            "desk": "cwg",
            "owner_id": "vett",
            "title": "t",
            "brief": "b",
            "success_criteria": "s",
        }
    )
    assert build.startswith("[BUILD_OBJECTIVE ")
    assert research.startswith("[RESEARCH_OBJECTIVE ")


def test_cos_relay_brief_is_partner_not_boss():
    from soveryn.rooms.store import build_cos_relay_brief

    text = build_cos_relay_brief(
        peer="vett",
        source_commission_id="abc",
        task="price check",
        result_text="MAP $12",
        ok=True,
        dm_session_id="dm1",
        room_session_id=None,
    )
    assert "Chief of Staff" not in text
    assert "Aetheria" in text
    assert "not managing" in text.lower()
