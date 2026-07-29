"""SOVERYN vNext — delegation background worker.

Drains tasks in 'dispatched' status and drives each through the execution
engine. SERIAL by design — one task at a time (git worktrees + a live repo
do not tolerate concurrent writers; a second worktree can start only after
the first has committed or been cleaned up).

Loop shape:
  while True:
      for task in store.list_tasks(status="dispatched"):
          try:
              execute_fn(task.id, store=..., repo_root=..., scotty_run=..., ...)
          except Exception:
              log and continue  ← one failing task must not kill the loop
      sleep(poll_seconds)

The ``_run_once_and_stop`` flag performs exactly one drain pass then returns.
Use it in tests so they don't block forever.

Public API
----------
run_forever(store, *, execute_fn, repo_root, scotty_run, run_acceptance,
            poll_seconds=5, _run_once_and_stop=False) -> None
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable

from soveryn.platform.delegation.store import DelegationStore

logger = logging.getLogger(__name__)


def run_forever(
    store: DelegationStore,
    *,
    execute_fn: Callable | None = None,
    repo_root: str | Path,
    scotty_run: Callable[[str, str, str], str],
    run_acceptance: Callable[[str, str], tuple[bool, str]],
    active_context=None,
    poll_seconds: float = 5.0,
    _run_once_and_stop: bool = False,
) -> None:
    """Drain dispatched delegation tasks in a serial loop.

    Parameters
    ----------
    store:
        Live DelegationStore to poll.
    execute_fn:
        ``(task_id, *, store, repo_root, scotty_run, run_acceptance) → None``
        Defaults to ``soveryn.platform.delegation.engine.execute_task``.
        Injectable for tests.
    repo_root:
        Root of the SOVERYN repository (passed through to execute_fn).
    scotty_run:
        ``(worktree_path, objective, scope) → summary:str``
        Scotty's bounded execution loop.  Passed through to execute_fn.
    run_acceptance:
        ``(worktree_path, acceptance) → (passed:bool, output:str)``
        Acceptance gate callable.  Passed through to execute_fn.
    poll_seconds:
        Seconds to sleep between drain passes.
    _run_once_and_stop:
        When True, perform exactly one drain pass and return.  Use in tests.
    """
    if execute_fn is None:
        from soveryn.platform.delegation.engine import execute_task
        execute_fn = execute_task

    repo_root = str(repo_root)

    # Crash recovery: any task left in 'executing' belongs to a previous process
    # that died mid-run (the worker is serial + single). Its worktree state is
    # unknown and unresumable, so mark it failed rather than leave it stranded,
    # and clean up its orphaned worktree/branch.
    _recover_stale_executing(store, repo_root=repo_root)

    while True:
        _drain(store, execute_fn=execute_fn, repo_root=repo_root,
               scotty_run=scotty_run, run_acceptance=run_acceptance,
               active_context=active_context)
        if _run_once_and_stop:
            return
        time.sleep(poll_seconds)


def _recover_stale_executing(store: DelegationStore, *, repo_root: str | Path | None = None) -> int:
    """Mark any task stuck in 'executing' as failed (stale after a crash), and
    best-effort clean up its orphaned worktree/branch.

    Returns the number of tasks recovered. Best-effort throughout: a store or git
    error on one task is logged and does not stop the sweep or the worker.
    """
    recovered = 0
    try:
        stale = store.list_tasks(status="executing")
    except Exception:
        logger.exception("delegation worker: could not list stale 'executing' tasks")
        return 0
    for task in stale:
        try:
            store.set_status(task.id, "failed")
            recovered += 1
        except Exception:
            logger.exception(
                "delegation worker: could not fail stale task %s", task.id
            )
            continue
        # Best-effort worktree/branch cleanup so orphans don't accumulate in the
        # live repo (they'd otherwise show as untracked and pin dead branches).
        wt_path = getattr(task, "worktree_path", None)
        branch = getattr(task, "branch", None)
        if repo_root and wt_path and branch:
            try:
                from soveryn.platform.delegation.worktree import remove_worktree
                remove_worktree(repo_root, wt_path, branch)
                logger.warning(
                    "delegation worker: recovered stale task %s → failed, worktree cleaned",
                    task.id,
                )
            except Exception:
                logger.exception(
                    "delegation worker: stale task %s failed; worktree %s needs manual cleanup",
                    task.id, wt_path,
                )
        else:
            logger.warning(
                "delegation worker: recovered stale 'executing' task %s → failed "
                "(worktree %s may need manual cleanup)",
                task.id, wt_path or "?",
            )
    return recovered


def _drain(
    store: DelegationStore,
    *,
    execute_fn: Callable,
    repo_root: str,
    scotty_run: Callable,
    run_acceptance: Callable,
    active_context=None,
) -> int:
    """Execute all currently dispatched tasks, serially. Returns count run."""
    tasks = store.list_tasks(status="dispatched")
    count = 0
    for task in tasks:
        try:
            execute_fn(
                task.id,
                store=store,
                repo_root=repo_root,
                scotty_run=scotty_run,
                run_acceptance=run_acceptance,
                active_context=active_context,
            )
            count += 1
        except Exception:
            logger.exception(
                "delegation worker: execute_fn failed for task %s — continuing",
                task.id,
            )
            count += 1  # still count it as attempted; loop must not stop
    return count
