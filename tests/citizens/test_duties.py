"""Duties: standing obligations registered first, rewired later."""
from __future__ import annotations

import pytest

from soveryn.citizens.duties import for_citizen, list_all, seed_founding, set_enabled
from soveryn.citizens.registry import Citizen, connect, register


@pytest.fixture()
def db(tmp_path):
    with connect(tmp_path / "citizens.db") as conn:
        for cid, name in (
            ("aetheria", "Aetheria"),
            ("vett", "V.E.T.T."),
            ("scotty", "Scotty"),
        ):
            register(conn, Citizen(id=cid, display_name=name))
        yield conn


def test_seed_founding_registers_heartbeat_for_aetheria(db):
    n = seed_founding(db)
    assert n >= 3
    kinds = {d["kind"] for d in for_citizen(db, "aetheria")}
    assert "heartbeat" in kinds
    assert "chat" in kinds
    hb = next(d for d in for_citizen(db, "aetheria") if d["kind"] == "heartbeat")
    assert hb["id"] == "aetheria:heartbeat"
    assert hb["enabled"] is True
    assert "1800" in (hb["schedule"] or "")


def test_seed_founding_registers_patrol_for_vett(db):
    seed_founding(db)
    kinds = {d["kind"] for d in for_citizen(db, "vett")}
    assert "patrol" in kinds


def test_seed_is_idempotent_and_preserves_disabled(db):
    seed_founding(db)
    set_enabled(db, "aetheria:heartbeat", enabled=False)
    seed_founding(db)
    hb = next(d for d in for_citizen(db, "aetheria") if d["kind"] == "heartbeat")
    assert hb["enabled"] is False
    assert len(list_all(db)) == len({d[0] for d in __import__(
        "soveryn.citizens.duties", fromlist=["FOUNDING_DUTIES"]
    ).FOUNDING_DUTIES})


def test_census_seeds_duties(tmp_path):
    from soveryn.citizens.census import take_census

    db = tmp_path / "citizens.db"
    with connect(db) as conn:
        rows = take_census(
            conn,
            workspaces=tmp_path / "desks",
            unit_check=lambda u: True,
            now="2026-08-14T12:00:00Z",
        )
    aeth = next(r for r in rows if r["id"] == "aetheria")
    assert "heartbeat" in aeth["duties_enabled"]
    assert "patrol" in next(r for r in rows if r["id"] == "vett")["duties_enabled"]
