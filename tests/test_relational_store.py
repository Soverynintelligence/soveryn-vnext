"""The relational memory — between-memories, gifts, and the bond.

The experiment's mechanism: memories create self. These tests pin the
honest minimum — valid parties only, gifts can't be self-given, bonds
recall what actually happened between two parties, claiming consumes.
"""
from __future__ import annotations

import pytest

from soveryn.platform.relational.store import (
    RelationalError,
    RelationalStore,
)


@pytest.fixture()
def store(tmp_path):
    return RelationalStore(tmp_path / "relational.db")


def test_encounter_records_between_pair_sorted(store):
    store.record_encounter(a="kernel", b="aetheria", kind="encounter",
                           note="built the lounge", recorded_by="kernel")
    store.record_encounter(a="aetheria", b="kernel", kind="celebration",
                           note="first green acceptance", recorded_by="aetheria")
    bond = store.recall_bond("aetheria", "kernel")
    assert len(bond["between"]) == 2  # pair is canonical, order-independent
    assert bond["between"][0]["note"] == "first green acceptance"  # newest first


def test_gift_cannot_be_self_given(store):
    with pytest.raises(RelationalError):
        store.leave_gift(from_party="kernel", to_party="kernel", note="hi me")


def test_unknown_party_rejected(store):
    with pytest.raises(RelationalError):
        store.leave_gift(from_party="kernel", to_party="grok", note="no")


def test_gift_claim_consumes(store):
    store.leave_gift(from_party="kernel", to_party="aetheria",
                     note="heads-up: the truth file rotate script is picky")
    store.leave_gift(from_party="eve", to_party="aetheria",
                     note="your brief made the blog draft better")
    claimed = store.claim_gifts("aetheria")
    assert {g.from_party for g in claimed} == {"kernel", "eve"}
    assert all(g.claimed_at for g in claimed)
    assert store.claim_gifts("aetheria") == []  # claimed once, gone
    assert store.unclaimed_count("aetheria") == 0


def test_bond_is_pair_scoped(store):
    store.record_encounter(a="kernel", b="aetheria", kind="note", note="ours",
                           recorded_by="kernel")
    store.record_encounter(a="eve", b="kernel", kind="note", note="different pair",
                           recorded_by="kernel")
    assert len(store.recall_bond("kernel", "aetheria")["between"]) == 1
    assert len(store.recall_bond("kernel", "eve")["between"]) == 1


def test_jon_is_a_valid_party(store):
    store.leave_gift(from_party="jon", to_party="kernel", note="nice work today")
    assert store.unclaimed_count("kernel") == 1


def test_empty_note_rejected(store):
    with pytest.raises(RelationalError):
        store.record_encounter(a="kernel", b="eve", kind="note", note="  ",
                               recorded_by="kernel")


def test_tools_registered_for_all_three_citizens():
    from soveryn.platform.relational.tools import build_relational_tools
    for owner in ("aetheria", "eve", "kernel"):
        specs = build_relational_tools(owner_agent=owner)
        names = {s.name for s in specs}
        assert {"bond_recall", "leave_gift", "record_encounter", "check_gifts"} <= names


def test_lounge_hook_records_encounter_for_lounge_only(tmp_path, monkeypatch):
    """The Lounge's ask_peer flow records between-memories; other rooms don't."""
    import json as _json
    from unittest.mock import MagicMock

    import sys
    sys.path.insert(0, "soveryn/app/routes")
    import importlib

    api_rooms = importlib.import_module("api_rooms")
    monkeypatch.setattr(
        api_rooms, "_data_root", lambda: tmp_path, raising=False
    )
    store = RelationalStore(tmp_path / "memory" / "relational.db")
    monkeypatch.setattr(
        "soveryn.platform.relational.store.DEFAULT_DB",
        tmp_path / "memory" / "relational.db",
    )
    (tmp_path / "rooms").mkdir(exist_ok=True)
    (tmp_path / "rooms" / "lounge.json").write_text(_json.dumps(
        {"session_id": "lounge-1"}
    ))

    api_rooms._record_lounge_encounter("lounge-1", "kernel", "aetheria", "first hangout")
    assert len(store.recall_bond("kernel", "aetheria")["between"]) == 1

    api_rooms._record_lounge_encounter("other-room", "kernel", "eve", "not the lounge")
    api_rooms._record_lounge_encounter("lounge-1", "aetheria", "aetheria", "self")
    api_rooms._record_lounge_encounter("lounge-1", "kernel", None, "no target")
    assert len(store.recall_bond("kernel", "aetheria")["between"]) == 1  # unchanged
