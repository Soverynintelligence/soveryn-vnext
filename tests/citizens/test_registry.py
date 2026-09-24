"""The registry may record what it is told, and report only what it has seen.

The charter makes status visible (§1.5) and accountability a duty (§5). That
only means something if `status` is DERIVED from evidence rather than stored as
an assertion — otherwise the registry is a place to write "resident" and have
the console repeat it.

The case that forces this is Scotty. He is a Citizen by name, soul and duty, but
he has no unit and no endpoint: he is invoked on demand. A registry that lets
someone write status='resident' for him would be asserting a live process that
does not exist — the same failure as a green light that was never read.
"""
from __future__ import annotations

import sqlite3

import pytest

from soveryn.citizens.registry import (
    Citizen,
    OBSERVED_ABSENT,
    OBSERVED_PRESENT,
    connect,
    list_citizens,
    observe,
    register,
    status_of,
)


@pytest.fixture()
def db(tmp_path):
    with connect(tmp_path / "citizens.db") as conn:
        yield conn


def _aetheria() -> Citizen:
    return Citizen(
        id="aetheria",
        display_name="Aetheria",
        soul_path="data/memory/souls/aetheria.md",
        model_server="aetheria_primary",
        workspace_path="~/soveryn_citizens/aetheria",
    )


def test_a_newly_registered_citizen_is_unobserved_not_offline(db):
    """Never looked is not the same fact as looked and found nothing."""
    register(db, _aetheria())
    assert status_of(db, "aetheria") == "unobserved"


def test_status_is_resident_only_after_a_positive_observation(db):
    register(db, _aetheria())
    observe(db, "aetheria", OBSERVED_PRESENT, at="2026-08-13T10:00:00Z")
    assert status_of(db, "aetheria") == "resident"


def test_a_failed_observation_reports_offline(db):
    register(db, _aetheria())
    observe(db, "aetheria", OBSERVED_ABSENT, at="2026-08-13T10:00:00Z")
    assert status_of(db, "aetheria") == "offline"


def test_the_latest_observation_wins(db):
    register(db, _aetheria())
    observe(db, "aetheria", OBSERVED_PRESENT, at="2026-08-13T10:00:00Z")
    observe(db, "aetheria", OBSERVED_ABSENT, at="2026-08-13T11:00:00Z")
    assert status_of(db, "aetheria") == "offline"


def test_last_seen_records_only_positive_observations(db):
    """`last_seen_at` means "was last seen alive", not "was last polled"."""
    register(db, _aetheria())
    observe(db, "aetheria", OBSERVED_PRESENT, at="2026-08-13T10:00:00Z")
    observe(db, "aetheria", OBSERVED_ABSENT, at="2026-08-13T11:00:00Z")
    row = next(c for c in list_citizens(db) if c["id"] == "aetheria")
    assert row["last_seen_at"] == "2026-08-13T10:00:00Z"
    assert row["status"] == "offline"


def test_status_cannot_be_written_directly(db):
    """The whole point: no one gets to assert residence into the table."""
    register(db, _aetheria())
    with pytest.raises(TypeError):
        register(db, _aetheria(), status="resident")  # type: ignore[call-arg]


def test_retired_is_a_grant_not_an_observation(db):
    """Retirement is Jon revoking standing (§6), so it outranks any probe."""
    register(db, _aetheria())
    observe(db, "aetheria", OBSERVED_PRESENT, at="2026-08-13T10:00:00Z")
    from soveryn.citizens.registry import retire
    retire(db, "aetheria")
    assert status_of(db, "aetheria") == "retired"


def test_observing_an_unregistered_citizen_is_refused(db):
    with pytest.raises(KeyError):
        observe(db, "ghost", OBSERVED_PRESENT, at="2026-08-13T10:00:00Z")


def test_registering_twice_updates_the_declaration_not_the_evidence(db):
    register(db, _aetheria())
    observe(db, "aetheria", OBSERVED_PRESENT, at="2026-08-13T10:00:00Z")
    changed = _aetheria()
    changed.notes = "moved desk"
    register(db, changed)
    row = next(c for c in list_citizens(db) if c["id"] == "aetheria")
    assert row["notes"] == "moved desk"
    assert row["last_seen_at"] == "2026-08-13T10:00:00Z"   # evidence survives


def test_list_is_ordered_and_complete(db):
    register(db, _aetheria())
    register(db, Citizen(id="vett", display_name="V.E.T.T.",
                         soul_path="data/memory/souls/vett.md",
                         model_server="vett_scotty_shared",
                         workspace_path="~/soveryn_citizens/vett"))
    ids = [c["id"] for c in list_citizens(db)]
    assert ids == ["aetheria", "vett"]


def test_schema_carries_duties_and_commissions(db):
    """Charter §9.1 names three tables; the registry ships all three."""
    names = {r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {"citizens", "duties", "commissions"} <= names


def test_a_citizen_row_survives_reopening_the_file(tmp_path):
    path = tmp_path / "citizens.db"
    with connect(path) as conn:
        register(conn, _aetheria())
        observe(conn, "aetheria", OBSERVED_PRESENT, at="2026-08-13T10:00:00Z")
    with connect(path) as conn:
        assert status_of(conn, "aetheria") == "resident"


def test_foreign_keys_are_enforced_for_duties(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO duties (id, citizen_id, kind, enabled) "
                   "VALUES ('d1', 'nobody', 'patrol', 1)")
