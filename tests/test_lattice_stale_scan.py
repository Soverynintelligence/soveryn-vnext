"""Fixture-DB tests for Lattice stale detectors (S5.1, D1–D4).

Mirrors the LatticeStore / tmp_path style of tests/test_lattice_teach.py and
tests/test_lattice.py. Seeds facts via LatticeStore.write_node (canonical_fact
+ entity + provenance.as_of). The scanner must never write.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from soveryn.platform.lattice.legacy import LatticeStore
from soveryn.platform.lattice.stale_scan import (
    CANONICAL_FACT_TAG,
    DETECTOR_COLLISION,
    DETECTOR_ORPHAN,
    DETECTOR_PIN,
    DETECTOR_TTL,
    HISTORICAL_SNAPSHOT_TAG,
    PinChecklistRow,
    lattice_stale_scan,
    main,
)

NOW = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path: Path) -> LatticeStore:
    return LatticeStore(tmp_path / "lattice.db")


def _write_fact(
    store: LatticeStore,
    content: str,
    *,
    entity: str | None = None,
    as_of: str | None = None,
    temporal_context: str | None = None,
    historical: bool = False,
    created_at: str | None = None,
    extra_tags: tuple[str, ...] = (),
) -> str:
    tags = [CANONICAL_FACT_TAG]
    if entity:
        tags.append(f"entity:{entity}")
    if historical:
        tags.append(HISTORICAL_SNAPSHOT_TAG)
    tags.extend(extra_tags)
    provenance: dict = {}
    if as_of is not None:
        provenance["as_of"] = as_of
    if temporal_context is not None:
        provenance["temporal_context"] = temporal_context
    node_id = store.write_node(
        "aetheria",
        content,
        node_type="fact",
        layer="global",
        tags=tuple(tags),
        provenance=provenance or None,
    )
    if created_at is not None:
        with store._conn() as conn:
            conn.execute(
                "UPDATE nodes SET created_at = ?, updated_at = ? WHERE id = ?",
                (created_at, created_at, node_id),
            )
    return node_id


def _write_supersedes(store: LatticeStore, source_id: str, target_id: str) -> str:
    now = datetime.now().isoformat()
    edge_id = str(uuid.uuid4())
    with store._conn() as conn:
        conn.execute(
            "INSERT INTO edges "
            "(id, source_id, target_id, relationship, strength, bidirectional, "
            "archived, reinforcement_count, reinforced_at, created_at) "
            "VALUES (?, ?, ?, 'supersedes', 1.0, 0, 0, 1, ?, ?)",
            (edge_id, source_id, target_id, now, now),
        )
    return edge_id


def test_d1_ttl_flags_old_as_of(store: LatticeStore) -> None:
    stale_id = _write_fact(
        store,
        "CWG ads PMax was live in March",
        entity="lab.notes.pmax",
        as_of="2026-01-01",
    )
    fresh_id = _write_fact(
        store,
        "House dinner is 6pm",
        entity="house.dinner",
        as_of="2026-09-10",
    )

    flags = lattice_stale_scan(store, now=NOW, pin_checklist=())

    d1 = [f for f in flags if f["detector"] == DETECTOR_TTL]
    assert len(d1) == 1
    assert d1[0]["lattice_id"] == stale_id
    assert d1[0]["entity"] == "lab.notes.pmax"
    assert d1[0]["severity"] == "low"
    assert "90" in d1[0]["summary"]
    assert "as_of" in d1[0]["summary"]
    assert "remember_fact" in d1[0]["suggested_action"]
    assert fresh_id not in {f["lattice_id"] for f in d1}

    # Prefix TTL: house.rule. is 180 days — 100-day-old rule stays quiet.
    _write_fact(
        store,
        "No LLM in the stale scanner",
        entity="house.rule.no-llm-scan",
        as_of="2026-06-03",
    )
    flags_after = lattice_stale_scan(store, now=NOW, pin_checklist=())
    d1_after = [f for f in flags_after if f["detector"] == DETECTOR_TTL]
    assert [f["lattice_id"] for f in d1_after] == [stale_id]


def test_d2_two_current_same_entity(store: LatticeStore) -> None:
    first = _write_fact(
        store, "Job is on hold", entity="cwg.job.acme", as_of="2026-09-01"
    )
    second = _write_fact(
        store, "Job is active", entity="cwg.job.acme", as_of="2026-09-10"
    )
    other = _write_fact(
        store, "Different job is live", entity="cwg.job.other", as_of="2026-09-10"
    )

    flags = lattice_stale_scan(store, now=NOW, pin_checklist=())
    d2 = [f for f in flags if f["detector"] == DETECTOR_COLLISION]
    assert len(d2) == 1
    assert d2[0]["entity"] == "cwg.job.acme"
    assert d2[0]["severity"] == "high"
    assert d2[0]["lattice_id"] in {first, second}
    assert first in d2[0]["summary"] and second in d2[0]["summary"]
    assert "close_and_supersede" in d2[0]["suggested_action"]
    assert other not in d2[0]["summary"]


def test_d3_pin_checklist_hit(store: LatticeStore, tmp_path: Path) -> None:
    lattice_id = _write_fact(
        store,
        "CWG PMax campaign is live this week",
        entity="cwg.ads.pmax",
        as_of="2026-09-10",
    )
    pin = tmp_path / "pinned_memory.md"
    pin.write_text(
        "# pins\n- cwg pmax: paused pending Jon\n",
        encoding="utf-8",
    )
    checklist = (
        PinChecklistRow("cwg.ads.pmax", "paused", "live"),
    )

    flags = lattice_stale_scan(
        store,
        now=NOW,
        pinned_path=pin,
        pin_checklist=checklist,
    )
    d3 = [f for f in flags if f["detector"] == DETECTOR_PIN]
    assert len(d3) == 1
    assert d3[0]["lattice_id"] == lattice_id
    assert d3[0]["entity"] == "cwg.ads.pmax"
    assert d3[0]["severity"] == "med"
    assert "paused" in d3[0]["summary"]
    assert "live" in d3[0]["summary"]

    # Inverse row: pin has lattice_needle, lattice has pin_needle.
    hold_id = _write_fact(
        store,
        "Travel plan is on hold",
        entity="house.travel",
        as_of="2026-09-10",
    )
    pin.write_text("travel is active\n", encoding="utf-8")
    inverse = (PinChecklistRow("house.travel", "hold", "active", invert=True),)
    inverted = lattice_stale_scan(
        store, now=NOW, pinned_path=pin, pin_checklist=inverse
    )
    d3_inv = [f for f in inverted if f["detector"] == DETECTOR_PIN]
    assert [f["lattice_id"] for f in d3_inv] == [hold_id]


def test_d4_orphan_historical(store: LatticeStore) -> None:
    orphan_id = _write_fact(
        store,
        "Old snapshot of the dinner rule",
        entity="house.dinner",
        as_of="2026-03-01",
        historical=True,
        created_at="2026-03-01T00:00:00+00:00",
    )

    flags = lattice_stale_scan(store, now=NOW, pin_checklist=())
    d4 = [f for f in flags if f["detector"] == DETECTOR_ORPHAN]
    assert len(d4) == 1
    assert d4[0]["lattice_id"] == orphan_id
    assert d4[0]["severity"] == "med"
    assert "no inbound supersedes" in d4[0]["summary"]
    assert "do not invent content" in d4[0]["suggested_action"]

    # Healthy close path: current supersedes historical → no D4.
    hist = _write_fact(
        store,
        "Prior dinner time",
        entity="house.dinner.healthy",
        historical=True,
        created_at="2026-01-01T00:00:00+00:00",
        as_of="2026-01-01",
    )
    current = _write_fact(
        store,
        "Dinner is 6pm",
        entity="house.dinner.healthy",
        as_of="2026-09-10",
        created_at="2026-09-10T00:00:00+00:00",
    )
    _write_supersedes(store, current, hist)
    healthy = lattice_stale_scan(store, now=NOW, pin_checklist=())
    healthy_ids = {
        f["lattice_id"]
        for f in healthy
        if f["detector"] == DETECTOR_ORPHAN
    }
    assert hist not in healthy_ids
    assert current not in healthy_ids
    assert orphan_id in healthy_ids

    # Dangling supersedes target.
    dangling_source = _write_fact(
        store, "Points at a ghost", entity="lab.ghost", as_of="2026-09-10"
    )
    missing = str(uuid.uuid4())
    now = datetime.now().isoformat()
    with store._conn() as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            "INSERT INTO edges "
            "(id, source_id, target_id, relationship, strength, bidirectional, "
            "archived, reinforcement_count, reinforced_at, created_at) "
            "VALUES (?, ?, ?, 'supersedes', 1.0, 0, 0, 1, ?, ?)",
            (str(uuid.uuid4()), dangling_source, missing, now, now),
        )
    dangling = lattice_stale_scan(store, now=NOW, pin_checklist=())
    assert any(
        f["detector"] == DETECTOR_ORPHAN and "missing id" in f["summary"]
        for f in dangling
    )


def test_digest_quiet_when_clean(store: LatticeStore, tmp_path: Path) -> None:
    hist = _write_fact(
        store,
        "Old value, properly closed",
        entity="house.rule.quiet",
        historical=True,
        created_at="2026-01-15T00:00:00+00:00",
        as_of="2026-01-15",
    )
    current = _write_fact(
        store,
        "Current house rule, confirmed this week",
        entity="house.rule.quiet",
        as_of="2026-09-08",
        created_at="2026-09-08T00:00:00+00:00",
    )
    _write_supersedes(store, current, hist)
    pin = tmp_path / "pinned_memory.md"
    pin.write_text("house.rule.quiet: confirmed this week\n", encoding="utf-8")

    flags = lattice_stale_scan(
        store,
        now=NOW,
        pinned_path=pin,
        pin_checklist=(PinChecklistRow("house.rule.quiet", "paused", "live"),),
    )
    assert flags == []


def test_scan_quiet_when_clean_empty_store(store: LatticeStore) -> None:
    assert lattice_stale_scan(store, now=NOW, pin_checklist=()) == []


def test_cli_quiet_json_exit_0(store: LatticeStore, tmp_path: Path, capsys) -> None:
    _write_fact(store, "Fresh fact", entity="lab.ok", as_of="2026-09-10")
    code = main(["--db", str(store.db_path), "--pinned", str(tmp_path / "missing.md")])
    captured = capsys.readouterr()
    assert code == 0
    assert json.loads(captured.out) == []


def test_scanner_does_not_write(store: LatticeStore) -> None:
    _write_fact(store, "Something old", entity="lab.notes.x", as_of="2025-01-01")
    before = _node_and_edge_counts(store)
    lattice_stale_scan(store, now=NOW, pin_checklist=())
    assert _node_and_edge_counts(store) == before


def _node_and_edge_counts(store: LatticeStore) -> tuple[int, int]:
    with sqlite3.connect(str(store.db_path)) as conn:
        nodes = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        edges = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    return nodes, edges
