"""The census may only report what it actually looked at.

The trap this guards is the one that made Aetheria read as offline on the public
Lab page: a citizen with nothing to probe rendering identically to a citizen
that was probed and found dead. Scotty has no unit by design, so the census must
leave him unobserved rather than manufacture an `absent` finding.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from soveryn.citizens.census import DESK_DIRS, make_desk, take_census
from soveryn.citizens.registry import connect


@pytest.fixture()
def db(tmp_path):
    with connect(tmp_path / "citizens.db") as conn:
        yield conn


def _by_id(rows):
    return {r["id"]: r for r in rows}


def test_a_desk_has_the_four_drawers(tmp_path):
    desk = make_desk(tmp_path, "aetheria")
    for sub in DESK_DIRS:
        assert (desk / sub).is_dir()


def test_making_a_desk_twice_disturbs_nothing(tmp_path):
    desk = make_desk(tmp_path, "vett")
    (desk / "notes" / "keep.md").write_text("work in progress")
    make_desk(tmp_path, "vett")
    assert (desk / "notes" / "keep.md").read_text() == "work in progress"


def test_all_units_down_reports_offline(db, tmp_path):
    rows = take_census(db, workspaces=tmp_path,
                       unit_check=lambda u: False, now="2026-08-13T10:00:00Z")
    assert _by_id(rows)["aetheria"]["status"] == "offline"


def test_any_unit_up_reports_resident(db, tmp_path):
    rows = take_census(db, workspaces=tmp_path,
                       unit_check=lambda u: u == "soveryn-heartbeat.service",
                       now="2026-08-13T10:00:00Z")
    aetheria = _by_id(rows)["aetheria"]
    assert aetheria["status"] == "resident"
    assert aetheria["last_observation"]["detail"] == "soveryn-heartbeat.service"


def test_scotty_is_never_observed_because_there_is_nothing_to_observe(db, tmp_path):
    """He has no unit. `offline` would assert a process that does not exist."""
    rows = take_census(db, workspaces=tmp_path,
                       unit_check=lambda u: False, now="2026-08-13T10:00:00Z")
    scotty = _by_id(rows)["scotty"]
    assert scotty["status"] == "unobserved"
    assert scotty["last_observation"] is None
    assert scotty["last_seen_at"] is None


def test_the_census_gives_every_citizen_a_desk(db, tmp_path):
    take_census(db, workspaces=tmp_path, unit_check=lambda u: False,
                now="2026-08-13T10:00:00Z")
    for who in ("aetheria", "vett", "scotty"):
        assert (tmp_path / who / "inbox").is_dir()


def test_a_probe_that_raises_counts_as_not_found_not_as_alive(db, tmp_path):
    def explode(unit):
        raise OSError("systemctl missing")
    from soveryn.citizens.census import _unit_is_active
    assert _unit_is_active("anything", runner=lambda *a, **k: explode(a)) is False


def test_running_the_census_twice_keeps_the_last_alive_time(db, tmp_path):
    take_census(db, workspaces=tmp_path, unit_check=lambda u: True,
                now="2026-08-13T10:00:00Z")
    rows = take_census(db, workspaces=tmp_path, unit_check=lambda u: False,
                       now="2026-08-13T11:00:00Z")
    vett = _by_id(rows)["vett"]
    assert vett["status"] == "offline"
    assert vett["last_seen_at"] == "2026-08-13T10:00:00Z"
