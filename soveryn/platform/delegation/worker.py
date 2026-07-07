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

    while True:
        _drain(store, execute_fn=execute_fn, repo_root=repo_root,
               scotty_run=scotty_run, run_acceptance=run_acceptance)
        if _run_once_and_stop:
            return
        time.sleep(poll_seconds)


def _drain(
    store: DelegationStore,
    *,
    execute_fn: Callable,
    repo_root: str,
    scotty_run: Callable,
    run_acceptance: Callable,
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
            )
            count += 1
        except Exception:
            logger.exception(
                "delegation worker: execute_fn failed for task %s — continuing",
                task.id,
            )
            count += 1  # still count it as attempted; loop must not stop
    return count
