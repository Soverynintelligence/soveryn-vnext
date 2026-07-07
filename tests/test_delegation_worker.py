"""Tests for the delegation background worker.

TDD: write failing tests first, then implement the worker.

Tests only cover the worker's drain/dispatch logic with injected fakes.
The live Scotty runner and the live worker thread are NOT tested here —
the worker's seam (execute_fn) is injectable for exactly this reason.
"""
from __future__ import annotations

import pytest

from soveryn.platform.delegation.store import DelegationStore
from soveryn.platform.delegation.worker import run_forever


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path) -> DelegationStore:
    """Real DelegationStore on a temp DB."""
    return DelegationStore(tmp_path / "delegation.db")


def _make_fake_execute():
    """Return (execute_fn, calls_list).

    execute_fn records calls as (task_id, kwargs) without touching the store
    (the worker only calls execute_fn; the real engine does the store work).
    """
    calls = []

    def execute_fn(task_id, *, store, repo_root, scotty_run, run_acceptance):
        calls.append({
            "task_id": task_id,
            "store": store,
            "repo_root": repo_root,
        })

    return execute_fn, calls


# ---------------------------------------------------------------------------
# Test 1: a single dispatched task is picked up and execute_fn called once
# ---------------------------------------------------------------------------

def test_dispatched_task_is_executed(store):
    task_id = store.create_task(
        dispatched_by="aetheria",
        objective="add a docstring",
        scope="soveryn/platform/delegation/__init__.py",
        acceptance="pytest tests/test_delegation_store.py -q",
    )

    execute_fn, calls = _make_fake_execute()
    run_forever(
        store,
        execute_fn=execute_fn,
        repo_root="/fake/repo",
        scotty_run=lambda wt, obj, scope: "done",
        run_acceptance=lambda wt, cmd: (True, "ok"),
        _run_once_and_stop=True,
    )

    assert len(calls) == 1
    assert calls[0]["task_id"] == task_id
    assert calls[0]["repo_root"] == "/fake/repo"
    assert calls[0]["store"] is store


# ---------------------------------------------------------------------------
# Test 2: two dispatched tasks are both executed, serially
# ---------------------------------------------------------------------------

def test_two_dispatched_tasks_executed_serially(store):
    id_a = store.create_task(
        dispatched_by="aetheria",
        objective="task A",
        scope="soveryn/platform/delegation/__init__.py",
        acceptance="pytest tests/ -q",
    )
    id_b = store.create_task(
        dispatched_by="aetheria",
        objective="task B",
        scope="soveryn/platform/delegation/__init__.py",
        acceptance="pytest tests/ -q",
    )

    execute_fn, calls = _make_fake_execute()
    run_forever(
        store,
        execute_fn=execute_fn,
        repo_root="/fake/repo",
        scotty_run=lambda wt, obj, scope: "done",
        run_acceptance=lambda wt, cmd: (True, "ok"),
        _run_once_and_stop=True,
    )

    # Both executed
    assert len(calls) == 2
    executed_ids = {c["task_id"] for c in calls}
    assert {id_a, id_b} == executed_ids


# ---------------------------------------------------------------------------
# Test 3: tasks in terminal / non-dispatched states are not executed
# ---------------------------------------------------------------------------

def test_non_dispatched_tasks_are_not_executed(store):
    # Create a dispatched task, then manually move it to each terminal-ish
    # state by using the store transitions. We use the full legal sequence for
    # in_review and landed/rejected/failed variants.

    # Task already executing (dispatched → executing)
    exec_id = store.create_task(
        dispatched_by="aetheria",
        objective="already executing",
        scope="soveryn/platform/delegation/__init__.py",
        acceptance="pytest tests/ -q",
    )
    store.set_status(exec_id, "executing")

    # Task already in_review (dispatched → executing → in_review)
    review_id = store.create_task(
        dispatched_by="aetheria",
        objective="in review",
        scope="soveryn/platform/delegation/__init__.py",
        acceptance="pytest tests/ -q",
    )
    store.set_status(review_id, "executing")
    store.set_status(review_id, "in_review")

    # Task failed (dispatched → failed directly — legal)
    failed_id = store.create_task(
        dispatched_by="aetheria",
        objective="failed",
        scope="soveryn/platform/delegation/__init__.py",
        acceptance="pytest tests/ -q",
    )
    store.set_status(failed_id, "failed")

    execute_fn, calls = _make_fake_execute()
    run_forever(
        store,
        execute_fn=execute_fn,
        repo_root="/fake/repo",
        scotty_run=lambda wt, obj, scope: "done",
        run_acceptance=lambda wt, cmd: (True, "ok"),
        _run_once_and_stop=True,
    )

    # None of the non-dispatched tasks should be picked up
    assert len(calls) == 0, f"Expected 0 calls, got {len(calls)}: {calls}"


# ---------------------------------------------------------------------------
# Test 4: a failing execute_fn does not kill the loop (other tasks still run)
# ---------------------------------------------------------------------------

def test_failing_execute_fn_does_not_abort_loop(store):
    id_a = store.create_task(
        dispatched_by="aetheria",
        objective="will fail",
        scope="soveryn/platform/delegation/__init__.py",
        acceptance="pytest tests/ -q",
    )
    id_b = store.create_task(
        dispatched_by="aetheria",
        objective="will succeed",
        scope="soveryn/platform/delegation/__init__.py",
        acceptance="pytest tests/ -q",
    )

    calls = []

    def flaky_execute(task_id, *, store, repo_root, scotty_run, run_acceptance):
        calls.append(task_id)
        if task_id == id_a:
            raise RuntimeError("simulated engine crash")

    run_forever(
        store,
        execute_fn=flaky_execute,
        repo_root="/fake/repo",
        scotty_run=lambda wt, obj, scope: "done",
        run_acceptance=lambda wt, cmd: (True, "ok"),
        _run_once_and_stop=True,
    )

    # Both tasks were attempted (loop did not abort on the first failure)
    assert len(calls) == 2
    assert set(calls) == {id_a, id_b}
