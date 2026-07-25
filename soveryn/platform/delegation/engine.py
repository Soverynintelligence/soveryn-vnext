"""SOVERYN vNext — delegation execution engine.

Drives a dispatched task through:
  1. Worktree isolation (throwaway git branch)
  2. Scotty's bounded loop (injected seam; real impl wired in Task 8)
  3. Acceptance gate
  4. Commit (green only) + status transition to in_review or failed

All seams are injected so the engine is testable without real git or Scotty.

Any exception anywhere → best-effort ``failed`` status + best-effort worktree
cleanup; never propagates out of ``execute_task``.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Callable

from soveryn.platform.delegation.store import DelegationStore
from soveryn.platform.delegation.worktree import (
    create_worktree,
    worktree_diff,
    remove_worktree as _default_remove_worktree,
)

logger = logging.getLogger(__name__)

# How many failed worktrees to keep on disk for post-mortem inspection before
# pruning the oldest. Retention is what makes a failure diagnosable; the cap is
# what stops retention from filling the disk.
FAILED_WORKTREE_RETENTION = 5


# ─── Default commit implementation ───────────────────────────────────────────

def _default_commit_fn(worktree_path: str, branch: str, message: str) -> None:
    """Commit all staged changes in *worktree_path* with *message*.

    ``worktree_diff`` already staged everything via ``git add -A``; we just
    need to commit.  Uses ``-a`` to pick up any unstaged residue.
    """
    subprocess.run(
        ["git", "-C", worktree_path, "commit", "-am", message],
        check=True,
        capture_output=True,
        text=True,
    )


# ─── Public API ──────────────────────────────────────────────────────────────

def execute_task(
    task_id: str,
    *,
    store: DelegationStore,
    repo_root: str | Path,
    scotty_run: Callable[[str, str, str], str],
    run_acceptance: Callable[[str, str], tuple[bool, str]],
    make_worktree: Callable[[str | Path, str], tuple[str, str]] = create_worktree,
    diff_fn: Callable[[str], str] = worktree_diff,
    commit_fn: Callable[[str, str, str], None] = _default_commit_fn,
    remove_worktree: Callable[[str | Path, str, str], None] = _default_remove_worktree,
    max_seconds: int = 600,
) -> None:
    """Drive *task_id* through isolated execution → verification → proposal.

    Parameters
    ----------
    task_id:
        ID of an existing ``dispatched`` delegation task.
    store:
        Live ``DelegationStore`` for this task.
    repo_root:
        Root of the SOVERYN repository (worktrees are created under
        ``<repo_root>/.worktrees/``).
    scotty_run:
        ``(worktree_path, objective, scope) → summary:str`` — Scotty's bounded
        loop.  Real implementation wired in Task 8; injected/faked in tests.
    run_acceptance:
        ``(worktree_path, acceptance) → (passed:bool, output:str)`` — runs the
        task's acceptance command inside the worktree.
    make_worktree:
        Factory for throwaway git worktrees.  Defaults to
        ``worktree.create_worktree``.
    diff_fn:
        Stages all changes and returns ``git diff --cached``.  Defaults to
        ``worktree.worktree_diff``.  Does NOT commit.
    commit_fn:
        Commits staged changes on the task branch.  Called only on green
        acceptance so the branch is mergeable at approve-time.
    remove_worktree:
        Cleanup callable; signature ``(repo_root, worktree_path, branch)``.
        Called on failure/exception; NOT called on green (branch must be
        retained for merge).
    max_seconds:
        Wall-clock cap passed to Scotty (not yet enforced here; forwarded as
        context in Task 8).
    """
    repo_root = str(repo_root)
    wt_path: str | None = None
    branch: str | None = None

    # ── Phase 1: transition to executing ─────────────────────────────────────
    try:
        store.set_status(task_id, "executing")
    except Exception:
        logger.exception("engine: could not transition task %s to executing", task_id)
        # Do NOT strand the task in 'dispatched' — best-effort terminal status
        # so a task always lands somewhere final (dispatched->failed is legal).
        try:
            store.set_status(task_id, "failed")
        except Exception:
            logger.exception("engine: could not set failed status for task %s", task_id)
        return  # no worktree created yet — nothing to clean up

    # ── Phase 2–7: main flow with exception guard ─────────────────────────────
    try:
        # 2. Create isolated worktree
        wt_path, branch = make_worktree(repo_root, task_id)
        store.set_execution(task_id, worktree_path=wt_path, branch=branch)

        # 3. Run Scotty's bounded loop
        task = store.get_task(task_id)
        summary = scotty_run(wt_path, task.objective, task.scope)

        # 4. Run acceptance gate
        passed, output = run_acceptance(wt_path, task.acceptance)

        # 5. Capture diff (stages but does not commit)
        diff = diff_fn(wt_path)

        # 6/7. Branch on acceptance result
        if passed:
            # Commit so the branch is mergeable at approve-time
            objective = task.objective
            commit_fn(wt_path, branch, f"task {task_id}: {objective}")
            store.set_result(task_id, diff=diff, test_output=output, summary=summary)
            store.set_status(task_id, "in_review")
            # Worktree RETAINED — approve-time merge needs it
            logger.info("engine: task %s passed acceptance → in_review", task_id)
        else:
            store.set_result(
                task_id,
                diff=diff,
                test_output=output,
                summary="acceptance tests failed",
            )
            store.set_status(task_id, "failed")
            logger.warning("engine: task %s failed acceptance → failed", task_id)
            # Worktree RETAINED on red (changed 2026-07-22). It is the only
            # forensic record of what Scotty actually did; deleting it is what
            # made the 8/8 empty-diff failures undiagnosable for 6 weeks.
            # Bounded retention keeps disk from growing without limit.
            _prune_failed_worktrees(remove_worktree, store, repo_root)

    except Exception:
        logger.exception("engine: unhandled exception for task %s", task_id)
        # Capture whatever landed in the worktree BEFORE anything else — a task
        # that RAISED (e.g. tool_round_limit, the actual Scotty failure mode)
        # otherwise recorded no diff at all, so the failure left zero evidence.
        if wt_path is not None:
            try:
                partial = diff_fn(wt_path)
                store.set_result(
                    task_id,
                    diff=partial,
                    test_output="",
                    summary="execution raised before acceptance",
                )
            except Exception:
                logger.exception(
                    "engine: could not capture partial diff for task %s", task_id
                )
        # Best-effort status transition (may already be in a terminal state)
        try:
            store.set_status(task_id, "failed")
        except Exception:
            logger.exception("engine: could not set failed status for task %s", task_id)
        # Worktree RETAINED on exception too — see the red-path note above.
        if wt_path is not None and branch is not None:
            _prune_failed_worktrees(remove_worktree, store, repo_root)


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _cleanup(
    remove_worktree_fn: Callable[[str | Path, str, str], None],
    repo_root: str,
    wt_path: str,
    branch: str,
) -> None:
    """Best-effort worktree removal; swallows all exceptions."""
    try:
        remove_worktree_fn(repo_root, wt_path, branch)
    except Exception:
        logger.exception(
            "engine: failed to remove worktree %s (branch %s) — may need manual cleanup",
            wt_path,
            branch,
        )


def _prune_failed_worktrees(
    remove_worktree_fn: Callable[[str | Path, str, str], None],
    store: DelegationStore,
    repo_root: str,
) -> None:
    """Retain the FAILED_WORKTREE_RETENTION most recent failed worktrees for
    inspection; remove the worktrees of older failed tasks.

    The current failing task's worktree is therefore always kept — it is the
    newest and sits well within the retention window. Only tasks that have
    fallen off the end of the window are cleaned up, and best-effort: a task
    whose worktree is already gone (or was never recorded) is skipped. The
    task row and its stored diff are never touched — only the on-disk worktree.
    """
    try:
        failed = store.list_tasks(status="failed")   # newest-first
    except Exception:
        logger.exception("engine: could not list failed tasks for worktree pruning")
        return

    for task in failed[FAILED_WORKTREE_RETENTION:]:
        wt = getattr(task, "worktree_path", None)
        branch = getattr(task, "branch", None)
        if not wt or not branch:
            continue
        if not Path(wt).exists():
            continue
        _cleanup(remove_worktree_fn, repo_root, wt, branch)
        logger.info(
            "engine: pruned aged failed worktree %s (task %s) beyond retention=%d",
            wt, task.id, FAILED_WORKTREE_RETENTION,
        )
