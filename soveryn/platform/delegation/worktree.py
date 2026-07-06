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
from pathlib import Path

logger = logging.getLogger(__name__)


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


def merge_worktree(repo_root: Path | str, branch: str) -> tuple[bool, str]:
    """Attempt a no-ff merge of *branch* into the current branch of *repo_root*.

    Returns
    -------
    (True, git_output)   on success.
    (False, message)     on conflict or any git error; best-effort abort so
                         the repo is not left mid-merge.
    """
    repo_root = Path(repo_root).resolve()

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
