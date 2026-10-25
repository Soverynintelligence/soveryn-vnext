"""A Forge/Kernel task is landed only when code proves it.

Forge fix 90e6ee41 was reported done but never reached main. These tests
pin the gate: commit not on main stays unlanded; a failing named test
stays unlanded with the reason; a stale (not reloaded) service stays
pending-verify; commit + test + reload together mark landed.
"""

from __future__ import annotations

from pathlib import Path

from soveryn.platform.delegation.landing import (
    FAILED,
    LANDED,
    PENDING_VERIFY,
    ReloadRecord,
    as_probe_records,
    evaluate_landing,
    mark_landed,
    recent_landing_probes,
)
from soveryn.platform.delegation.store import DelegationStore

COMMIT = "90e6ee41"
TEST_NAME = "tests/test_medic.py"
SERVICE = "soveryn-vnext.service"
COMMIT_AT = "2026-10-25T12:00:00Z"
AFTER = "2026-10-25T13:00:00Z"
BEFORE = "2026-10-25T11:00:00Z"


def _store(tmp_path: Path) -> DelegationStore:
    return DelegationStore(tmp_path / "delegation.db")


def _in_review(store: DelegationStore) -> str:
    tid = store.create_task(
        dispatched_by="aetheria",
        objective="Land the medic retired-units regression.",
        scope="tests/test_medic.py",
        acceptance=f"python -m pytest {TEST_NAME} -q",
    )
    store.set_status(tid, "executing")
    store.set_status(tid, "in_review")
    return tid


def _facts(**extra):
    base = dict(
        commit=COMMIT,
        test_name=TEST_NAME,
        service=SERVICE,
        on_main=True,
        test_passed=True,
        test_output="1 passed",
        commit_at=COMMIT_AT,
        unit_started_at=AFTER,
    )
    base.update(extra)
    return base


def test_commit_not_on_main_stays_unlanded(tmp_path):
    store = _store(tmp_path)
    tid = _in_review(store)
    verdict = mark_landed(store, tid, **_facts(on_main=False))
    assert verdict.landed is False
    assert verdict.status != LANDED
    assert store.get_task(tid).status != LANDED
    assert COMMIT in verdict.reason
    assert "not reachable from main" in verdict.reason


def test_failing_test_stays_unlanded_with_reason(tmp_path):
    store = _store(tmp_path)
    tid = _in_review(store)
    verdict = mark_landed(
        store,
        tid,
        **_facts(test_passed=False, test_output="1 failed: test_retired_units"),
    )
    assert verdict.landed is False
    assert verdict.status == FAILED
    assert store.get_task(tid).status != LANDED
    assert TEST_NAME in verdict.reason
    assert "failed" in verdict.reason
    assert "test_retired_units" in verdict.reason
    assert store.get_task(tid).review_feedback == verdict.reason


def test_stale_service_stays_pending_verify(tmp_path):
    store = _store(tmp_path)
    tid = _in_review(store)
    verdict = mark_landed(
        store,
        tid,
        **_facts(unit_started_at=BEFORE, reload=None),
    )
    assert verdict.status == PENDING_VERIFY
    assert verdict.landed is False
    assert store.get_task(tid).status == PENDING_VERIFY
    assert SERVICE in verdict.reason
    assert "not been reloaded" in verdict.reason


def test_all_three_pass_marks_landed(tmp_path):
    store = _store(tmp_path)
    tid = _in_review(store)
    verdict = mark_landed(store, tid, **_facts())
    assert verdict.status == LANDED
    assert verdict.landed is True
    assert store.get_task(tid).status == LANDED
    assert evaluate_landing(**_facts()).landed is True


def test_explicit_reload_record_covers_a_stale_unit_start(tmp_path):
    """Unit start before the commit is fine when a reload was recorded after."""
    store = _store(tmp_path)
    tid = _in_review(store)
    reload = ReloadRecord(service=SERVICE, reloaded_at=AFTER, commit=COMMIT)
    verdict = mark_landed(
        store,
        tid,
        **_facts(unit_started_at=BEFORE, reload=reload),
    )
    assert verdict.status == LANDED
    assert store.get_task(tid).status == LANDED


def test_failing_proof_writes_through_store_and_feeds_outage_gate(tmp_path):
    """mark_landed re-reads the ledger row; probe() is a real outage-gate record."""
    from soveryn.platform.inference.outage import (
        ProbeRecord,
        apply_outage_gate,
        merge_tick_probes,
        should_block_dispatch,
    )

    store = _store(tmp_path)
    tid = _in_review(store)
    verdict = mark_landed(
        store,
        tid,
        **_facts(test_passed=False, test_output="1 failed: test_retired_units"),
    )
    row = store.get_task(tid)
    assert row is not None
    assert row.status == FAILED
    assert row.id == tid
    persisted = recent_landing_probes(path=tmp_path / "landing_probes.jsonl")
    assert persisted and persisted[-1]["name"] == "landing_proof"
    assert persisted[-1]["result"] == "fail"
    assert "test_retired_units" in persisted[-1]["detail"]

    probe = verdict.as_probe_record()
    assert isinstance(probe, ProbeRecord)
    assert probe.name == "landing_proof"
    assert probe.result == "fail"
    ok_brain = ProbeRecord(
        target="http://10.10.10.2:8888",
        timestamp="2026-10-25T13:50:00Z",
        result="ok",
        name="kernel_build",
    )
    invented = "build brain on 127.0.0.1:8080 is down; blocked Forge until it returns."
    merged = merge_tick_probes((ok_brain,), as_probe_records(persisted))
    gate = apply_outage_gate(invented, merged)
    assert any(row["name"] == "landing_proof" for row in gate.reported)
    assert "8080" not in gate.text
    assert should_block_dispatch(merged) is True
