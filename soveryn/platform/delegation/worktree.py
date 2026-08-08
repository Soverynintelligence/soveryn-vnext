"""
soveryn.platform.delegation.worktree
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Git worktree manager for Scotty's delegated execution.

Isolates code edits in a throwaway worktree; provides diff, merge, and
cleanup primitives.  All git I/O goes through subprocess.run(["git", ...])
with captured output — no shell=True, no git Python libraries.
"""

from __future__ import annotations

import logging
import subprocess
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

# Serializes operations that mutate the LIVE repo's shared git state (worktree
# add/remove/prune + merge). The approve route (a Flask request thread) can call
# merge_worktree while the delegation worker thread is calling create_worktree /
# remove_worktree; without this lock those race on .git/worktrees and refs.
# Commit happens inside a worktree's own index (different working tree) and is
# not covered here — git's own index.lock guards the object store.
_REPO_GIT_LOCK = threading.Lock()


def _git(repo_root: Path | str, *args: str) -> str:
    """Run `git -C <repo_root> <args>` and return stdout."""
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_worktree(repo_root: Path | str, task_id: str) -> tuple[str, str]:
    """Create a git worktree for *task_id* under ``<repo_root>/.worktrees/``.

    Returns
    -------
    (worktree_path, branch)
        *worktree_path* — absolute path to the new worktree (str).
        *branch* — ``task/<task_id>``.
    """
    repo_root = Path(repo_root).resolve()
    branch = f"task/{task_id}"
    wt_path = repo_root / ".worktrees" / task_id

    # Ensure parent exists (git won't create it for us when using sub-dirs)
    wt_path.parent.mkdir(parents=True, exist_ok=True)

    with _REPO_GIT_LOCK:
        _git(repo_root, "worktree", "add", str(wt_path), "-b", branch, "HEAD")

    logger.debug("created worktree %s on branch %s", wt_path, branch)
    return str(wt_path), branch


def worktree_diff(worktree_path: Path | str) -> str:
    """Stage all changes in *worktree_path* and return the cached diff.

    This only stages + diffs; it does NOT commit.  The engine (a later task)
    is responsible for committing when it wants to land the changes.

    Returns the raw ``git diff --cached`` output (empty string if nothing
    changed).
    """
    wt = Path(worktree_path).resolve()

    # Stage everything so the diff captures new/deleted/modified files.
    _git(wt, "add", "-A")

    # Return the staged diff; may be empty if nothing changed.
    return _git(wt, "diff", "--cached")


def current_branch(repo_root: Path | str) -> str:
    """Return the checked-out branch name of *repo_root* (empty on detached/err)."""
    try:
        out = _git(repo_root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    except subprocess.CalledProcessError:
        return ""
    return "" if out == "HEAD" else out


def merge_worktree(
    repo_root: Path | str, branch: str, *, into: str | None = "main"
) -> tuple[bool, str]:
    """Attempt a no-ff merge of *branch* into the current branch of *repo_root*.

    Safety guard: when *into* is set (default ``"main"``), the merge is REFUSED
    unless *repo_root* is actually on that branch. This prevents landing Scotty's
    task branch onto whatever branch the live repo happens to be sitting on — a
    stray feature branch, a detached HEAD — instead of the intended integration
    branch. Pass ``into=None`` to merge into the current branch unconditionally
    (used by tests).

    Returns
    -------
    (True, git_output)   on success.
    (False, message)     on wrong-branch refusal, conflict, or any git error;
                         best-effort abort so the repo is not left mid-merge.
    """
    repo_root = Path(repo_root).resolve()

    with _REPO_GIT_LOCK:
        if into is not None:
            cur = current_branch(repo_root)
            if cur != into:
                msg = (
                    f"refusing to merge {branch!r}: repo is on {cur or '(detached)'!r}, "
                    f"not the integration branch {into!r}. Check out {into!r} first."
                )
                logger.warning("merge_worktree: %s", msg)
                return False, msg

        try:
            output = _git(repo_root, "merge", "--no-ff", "--no-edit", branch)
            logger.debug("merge succeeded: %s", output.strip())
            return True, output
        except subprocess.CalledProcessError as exc:
            message = exc.stderr or exc.stdout or str(exc)
            logger.warning("merge failed (%s), aborting: %s", branch, message)

            # Best-effort abort — swallow errors so we don't mask the original.
            try:
                subprocess.run(
                    ["git", "-C", str(repo_root), "merge", "--abort"],
                    capture_output=True,
                    text=True,
                )
            except Exception:
                pass

            return False, message.strip()


def preserve_branch(repo_root: Path | str, branch: str, tag: str) -> str | None:
    """Tag a branch's head so its work survives the branch being deleted.

    Rejecting a task calls ``remove_worktree`` with ``delete_branch=True``, which
    runs ``git branch -D``. That leaves the commit as a dangling object — still
    recoverable by sha, and gone at the next ``git gc``.

    On 2026-08-07 a rejected task took 1,138 lines of working, tested code with
    it. The work was recovered only because someone checked whether the branch
    still existed; the rejection reported success either way, and the review
    feedback told the agent to "build from branch task/…" — a branch the same
    request had just destroyed.

    Rejection should be reversible. A tag costs nothing, keeps the branch list
    clean, and names why it exists. Returns the tag name, or None if tagging
    failed — callers must treat None as "the work is NOT preserved", never as
    routine.
    """
    repo_root = Path(repo_root).resolve()
    try:
        with _REPO_GIT_LOCK:
            _git(repo_root, "rev-parse", "--verify", branch)
            _git(repo_root, "tag", "-f", tag, branch)
        logger.info("preserved %s as tag %s before deletion", branch, tag)
        return tag
    except Exception:
        logger.exception(
            "preserve_branch: could not tag %s as %s — the work will be LOST "
            "when the branch is deleted", branch, tag,
        )
        return None


def remove_worktree(
    repo_root: Path | str,
    worktree_path: Path | str,
    branch: str,
    *,
    delete_branch: bool = True,
) -> None:
    """Remove a worktree and optionally delete its tracking branch.

    Steps:
    1. ``git worktree remove --force <worktree_path>``
    2. ``git branch -D <branch>`` (if *delete_branch*)
    3. ``git worktree prune``

    All steps are best-effort after the initial removal; errors are logged but
    not re-raised so cleanup doesn't propagate into the engine.
    """
    repo_root = Path(repo_root).resolve()

    with _REPO_GIT_LOCK:
        try:
            _git(repo_root, "worktree", "remove", "--force", str(worktree_path))
            logger.debug("removed worktree %s", worktree_path)
        except subprocess.CalledProcessError as exc:
            logger.error("failed to remove worktree %s: %s", worktree_path, exc.stderr)
            # Not re-raised — carry on with branch delete + prune.

        if delete_branch:
            try:
                _git(repo_root, "branch", "-D", branch)
                logger.debug("deleted branch %s", branch)
            except subprocess.CalledProcessError as exc:
                logger.warning("could not delete branch %s: %s", branch, exc.stderr)

        try:
            _git(repo_root, "worktree", "prune")
        except subprocess.CalledProcessError as exc:
            logger.warning("worktree prune failed: %s", exc.stderr)
