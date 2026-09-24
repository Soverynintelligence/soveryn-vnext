"""A commission is work the house is owed, so it may not be lost or done twice.

Three failures this guards, in order of how expensive they are:

  double-claim  two workers take the same commission and both act. For a
                citizen whose duties touch the real world — Scotty repairing,
                Vett publishing — that is the work happening twice.
  silent loss   a worker dies mid-commission and the row sits in `running`
                forever. Nothing failed, nothing completed, and no one is told.
  false success a commission marked done with no evidence of what it produced.

The claim is therefore a single guarded UPDATE, not read-then-write, and
`running` carries who claimed it and when so an abandoned one is findable
rather than merely regrettable.
"""
from __future__ import annotations

import pytest

from soveryn.citizens.commissions import (
    abandoned,
    claim,
    complete,
    enqueue,
    fail,
    for_citizen,
    requeue,
)
from soveryn.citizens.registry import Citizen, connect, register


@pytest.fixture()
def db(tmp_path):
    with connect(tmp_path / "citizens.db") as conn:
        register(conn, Citizen(id="vett", display_name="V.E.T.T."))
        register(conn, Citizen(id="scotty", display_name="Scotty"))
        yield conn


def test_enqueued_work_is_queued_and_attributed(db):
    cid = enqueue(db, "vett", "verify the Standard Oil citations",
                  at="2026-08-14T09:00:00Z")
    (row,) = for_citizen(db, "vett")
    assert row["id"] == cid
    assert row["state"] == "queued"
    assert row["body"] == "verify the Standard Oil citations"
    assert row["created_at"] == "2026-08-14T09:00:00Z"


def test_a_commission_for_an_unknown_citizen_is_refused(db):
    with pytest.raises(Exception):
        enqueue(db, "ghost", "do something", at="2026-08-14T09:00:00Z")


def test_claiming_moves_it_to_running_and_records_the_worker(db):
    enqueue(db, "vett", "task", at="2026-08-14T09:00:00Z")
    got = claim(db, "vett", worker="worker-1", at="2026-08-14T09:01:00Z")
    assert got is not None
    assert got["state"] == "running"
    assert got["claimed_by"] == "worker-1"
    assert got["claimed_at"] == "2026-08-14T09:01:00Z"


def test_two_workers_cannot_claim_the_same_commission(db):
    enqueue(db, "vett", "the only task", at="2026-08-14T09:00:00Z")
    first = claim(db, "vett", worker="worker-1", at="2026-08-14T09:01:00Z")
    second = claim(db, "vett", worker="worker-2", at="2026-08-14T09:01:00Z")
    assert first is not None
    assert second is None, "the second worker took work already claimed"


def test_claiming_takes_the_oldest_first(db):
    old = enqueue(db, "vett", "first", at="2026-08-14T09:00:00Z")
    enqueue(db, "vett", "second", at="2026-08-14T10:00:00Z")
    got = claim(db, "vett", worker="w", at="2026-08-14T10:01:00Z")
    assert got["id"] == old


def test_a_worker_only_claims_its_own_citizens_work(db):
    enqueue(db, "scotty", "repair the thing", at="2026-08-14T09:00:00Z")
    assert claim(db, "vett", worker="w", at="2026-08-14T09:01:00Z") is None


def test_claiming_an_empty_queue_returns_none(db):
    assert claim(db, "vett", worker="w", at="2026-08-14T09:01:00Z") is None


def test_completing_requires_evidence_of_what_it_produced(db):
    cid = enqueue(db, "vett", "task", at="2026-08-14T09:00:00Z")
    claim(db, "vett", worker="w", at="2026-08-14T09:01:00Z")
    with pytest.raises(ValueError):
        complete(db, cid, result_ref="", at="2026-08-14T09:05:00Z")


def test_completing_records_the_result_and_the_time(db):
    cid = enqueue(db, "vett", "task", at="2026-08-14T09:00:00Z")
    claim(db, "vett", worker="w", at="2026-08-14T09:01:00Z")
    complete(db, cid, result_ref="~/soveryn_citizens/vett/outbox/report.md",
             at="2026-08-14T09:05:00Z")
    (row,) = for_citizen(db, "vett")
    assert row["state"] == "done"
    assert row["completed_at"] == "2026-08-14T09:05:00Z"
    assert row["result_ref"].endswith("report.md")


def test_failing_records_why(db):
    cid = enqueue(db, "vett", "task", at="2026-08-14T09:00:00Z")
    claim(db, "vett", worker="w", at="2026-08-14T09:01:00Z")
    fail(db, cid, error="model unreachable", at="2026-08-14T09:05:00Z")
    (row,) = for_citizen(db, "vett")
    assert row["state"] == "failed"
    assert row["error"] == "model unreachable"
    assert row["completed_at"] == "2026-08-14T09:05:00Z"


def test_only_a_running_commission_can_be_completed(db):
    cid = enqueue(db, "vett", "task", at="2026-08-14T09:00:00Z")
    with pytest.raises(ValueError):
        complete(db, cid, result_ref="x", at="2026-08-14T09:05:00Z")


def test_a_completed_commission_complete_again_is_idempotent(db):
    cid = enqueue(db, "vett", "task", at="2026-08-14T09:00:00Z")
    claim(db, "vett", worker="w", at="2026-08-14T09:01:00Z")
    complete(db, cid, result_ref="x", at="2026-08-14T09:05:00Z")
    complete(db, cid, result_ref="x again", at="2026-08-14T09:06:00Z")
    (row,) = for_citizen(db, "vett")
    assert row["state"] == "done"
    assert row["result_ref"] == "x"  # first evidence kept


def test_complete_recovers_from_intervening_fail(db):
    """Worker still finishing must not lose to a premature fail (Kernel smoke)."""
    cid = enqueue(db, "vett", "task", at="2026-08-14T09:00:00Z")
    claim(db, "vett", worker="w", at="2026-08-14T09:01:00Z")
    fail(db, cid, error="smoke cancelled — wiring probe only", at="2026-08-14T09:02:00Z")
    complete(
        db,
        cid,
        result_ref="~/soveryn_citizens/vett/outbox/late.md",
        at="2026-08-14T09:05:00Z",
    )
    (row,) = for_citizen(db, "vett")
    assert row["state"] == "done"
    assert row["result_ref"].endswith("late.md")
    assert "smoke cancelled" in (row["error"] or "")
    assert "recovered by complete" in (row["error"] or "")


def test_fail_after_done_is_refused(db):
    cid = enqueue(db, "vett", "task", at="2026-08-14T09:00:00Z")
    claim(db, "vett", worker="w", at="2026-08-14T09:01:00Z")
    complete(db, cid, result_ref="x", at="2026-08-14T09:05:00Z")
    with pytest.raises(ValueError, match="already done"):
        fail(db, cid, error="too late", at="2026-08-14T09:06:00Z")


def test_work_claimed_and_never_finished_is_findable(db):
    """A worker that dies leaves `running` behind. Silence is the bug."""
    enqueue(db, "vett", "task", at="2026-08-14T09:00:00Z")
    claim(db, "vett", worker="doomed", at="2026-08-14T09:00:00Z")
    assert abandoned(db, claimed_before="2026-08-14T09:30:00Z") != []
    assert abandoned(db, claimed_before="2026-08-14T08:00:00Z") == []


def test_abandoned_work_can_be_put_back_on_the_queue(db):
    cid = enqueue(db, "vett", "task", at="2026-08-14T09:00:00Z")
    claim(db, "vett", worker="doomed", at="2026-08-14T09:00:00Z")
    requeue(db, cid, at="2026-08-14T10:00:00Z", reason="worker died")
    (row,) = for_citizen(db, "vett")
    assert row["state"] == "queued"
    assert row["claimed_by"] is None
    # The attempt is not erased — it is why anyone would look.
    assert "worker died" in (row["error"] or "")
    assert claim(db, "vett", worker="w2", at="2026-08-14T10:01:00Z") is not None


def test_for_citizen_is_newest_first_and_scoped(db):
    enqueue(db, "vett", "older", at="2026-08-14T09:00:00Z")
    enqueue(db, "vett", "newer", at="2026-08-14T11:00:00Z")
    enqueue(db, "scotty", "not vett's", at="2026-08-14T10:00:00Z")
    bodies = [r["body"] for r in for_citizen(db, "vett")]
    assert bodies == ["newer", "older"]


def test_no_commission_is_ever_handed_to_two_workers(tmp_path):
    """The sequential double-claim test is not enough, and here is the proof.

    The first implementation of claim() updated the row, then re-SELECTed it by
    (worker, claimed_at) — a key that is not unique. Every sequential test
    passed. Under 12 threads it marked all 200 commissions `running` while
    handing back only 2, both of them twice: the exact double-execution the
    function exists to prevent.

    A queue whose correctness depends on nobody racing it is not a queue.
    """
    import collections
    import sqlite3
    import threading

    from soveryn.citizens.registry import Citizen, connect, register

    path = tmp_path / "race.db"
    total, workers = 120, 8
    with connect(path) as conn:
        register(conn, Citizen(id="vett", display_name="V.E.T.T."))
        for i in range(total):
            enqueue(conn, "vett", f"task {i}", at=f"2026-08-14T09:{i:04d}Z")

    handed_out: dict[str, list[int]] = collections.defaultdict(list)
    lock = threading.Lock()
    start = threading.Barrier(workers)

    def work(w: int) -> None:
        conn = sqlite3.connect(str(path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        start.wait()
        while True:
            try:
                row = claim(conn, "vett", worker=f"w{w}", at="2026-08-14T10:00:00Z")
            except sqlite3.OperationalError:
                continue          # write-lock contention: retry, never drop work
            if row is None:
                break
            with lock:
                handed_out[row["id"]].append(w)
        conn.close()

    threads = [threading.Thread(target=work, args=(w,)) for w in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    twice = {k: v for k, v in handed_out.items() if len(v) > 1}
    assert not twice, f"{len(twice)} commissions handed to more than one worker"
    assert len(handed_out) == total, "commissions were marked claimed but never handed out"

    with connect(path) as conn:
        left = conn.execute(
            "SELECT COUNT(*) c FROM commissions WHERE state = 'queued'"
        ).fetchone()["c"]
    assert left == 0
