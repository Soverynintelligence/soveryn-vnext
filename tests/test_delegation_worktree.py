"""Tests for soveryn.platform.delegation.worktree — hermetic (builds own temp git repos)."""
import subprocess
from pathlib import Path

import pytest

from soveryn.platform.delegation.worktree import (
    create_worktree,
    merge_worktree,
    remove_worktree,
    worktree_diff,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _init_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo with a single commit and return its path."""
    r = tmp_path / "repo"
    r.mkdir()

    def g(*args):
        subprocess.run(["git", "-C", str(r), *args], check=True, capture_output=True, text=True)

    g("init", "-b", "main")
    g("config", "user.email", "t@t")
    g("config", "user.name", "t")
    (r / "f.txt").write_text("base\n")
    g("add", "-A")
    g("commit", "-m", "base")
    return r


def _worktree_list(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "list"],
        check=True, capture_output=True, text=True,
    )
    return result.stdout


def _file_content(repo_root: Path, filename: str) -> str:
    return (repo_root / filename).read_text()


# ---------------------------------------------------------------------------
# create_worktree
# ---------------------------------------------------------------------------

def test_create_worktree_path_exists(tmp_path):
    repo = _init_repo(tmp_path)
    wt_path, branch = create_worktree(repo, "abc123")
    assert Path(wt_path).exists(), "worktree directory must exist on disk"


def test_create_worktree_branch_name(tmp_path):
    repo = _init_repo(tmp_path)
    _, branch = create_worktree(repo, "abc123")
    assert branch == "task/abc123"


def test_create_worktree_appears_in_git_list(tmp_path):
    repo = _init_repo(tmp_path)
    wt_path, _ = create_worktree(repo, "abc123")
    listing = _worktree_list(repo)
    assert str(wt_path) in listing, "worktree must appear in `git worktree list`"


def test_create_worktree_correct_location(tmp_path):
    repo = _init_repo(tmp_path)
    wt_path, _ = create_worktree(repo, "myid")
    expected = repo / ".worktrees" / "myid"
    assert Path(wt_path) == expected


# ---------------------------------------------------------------------------
# worktree_diff
# ---------------------------------------------------------------------------

def test_worktree_diff_shows_change(tmp_path):
    repo = _init_repo(tmp_path)
    wt_path, _ = create_worktree(repo, "difftest")
    # Modify a file in the worktree
    (Path(wt_path) / "f.txt").write_text("modified\n")
    diff = worktree_diff(wt_path)
    assert "modified" in diff or "-base" in diff, "diff must reflect the file change"


def test_worktree_diff_empty_when_no_changes(tmp_path):
    repo = _init_repo(tmp_path)
    wt_path, _ = create_worktree(repo, "nodiff")
    diff = worktree_diff(wt_path)
    assert diff.strip() == "", "diff must be empty when nothing changed"


def test_worktree_diff_new_file(tmp_path):
    repo = _init_repo(tmp_path)
    wt_path, _ = create_worktree(repo, "newfile")
    (Path(wt_path) / "new.txt").write_text("hello\n")
    diff = worktree_diff(wt_path)
    assert "new.txt" in diff, "diff must include the new file"


# ---------------------------------------------------------------------------
# merge_worktree (success path)
# ---------------------------------------------------------------------------

def test_merge_worktree_success(tmp_path):
    repo = _init_repo(tmp_path)
    wt_path, branch = create_worktree(repo, "mergeok")
    # Make a commit inside the worktree
    (Path(wt_path) / "f.txt").write_text("from worktree\n")
    subprocess.run(
        ["git", "-C", str(wt_path), "commit", "-am", "worktree change"],
        check=True, capture_output=True, text=True,
    )
    ok, msg = merge_worktree(repo, branch)
    assert ok is True, f"merge should succeed; got: {msg}"


def test_merge_worktree_lands_change_on_main(tmp_path):
    repo = _init_repo(tmp_path)
    wt_path, branch = create_worktree(repo, "landtest")
    (Path(wt_path) / "f.txt").write_text("landed\n")
    subprocess.run(
        ["git", "-C", str(wt_path), "commit", "-am", "land this"],
        check=True, capture_output=True, text=True,
    )
    merge_worktree(repo, branch)
    # The main repo should now have the updated file
    content = _file_content(repo, "f.txt")
    assert content == "landed\n", "merged change must appear on main branch"


# ---------------------------------------------------------------------------
# merge_worktree (conflict path)
# ---------------------------------------------------------------------------

def test_merge_worktree_conflict_returns_false(tmp_path):
    repo = _init_repo(tmp_path)
    wt_path, branch = create_worktree(repo, "conflicttest")

    # Make a conflicting change in the worktree (same line, different content)
    (Path(wt_path) / "f.txt").write_text("worktree version\n")
    subprocess.run(
        ["git", "-C", str(wt_path), "commit", "-am", "wt change"],
        check=True, capture_output=True, text=True,
    )

    # Also advance main with a conflicting change (different content, same file/line)
    # Switch to main, modify f.txt, commit
    subprocess.run(
        ["git", "-C", str(repo), "checkout", "main"],
        check=True, capture_output=True, text=True,
    )
    (repo / "f.txt").write_text("main version\n")
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-am", "main change"],
        check=True, capture_output=True, text=True,
    )

    ok, msg = merge_worktree(repo, branch)
    assert ok is False, "conflict must return (False, ...)"
    assert isinstance(msg, str) and len(msg) > 0


def test_merge_worktree_conflict_leaves_repo_clean(tmp_path):
    """After a failed merge, the repo must not be in mid-merge state."""
    repo = _init_repo(tmp_path)
    wt_path, branch = create_worktree(repo, "cleantest")

    (Path(wt_path) / "f.txt").write_text("wt\n")
    subprocess.run(
        ["git", "-C", str(wt_path), "commit", "-am", "wt"],
        check=True, capture_output=True, text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "checkout", "main"],
        check=True, capture_output=True, text=True,
    )
    (repo / "f.txt").write_text("main\n")
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-am", "main"],
        check=True, capture_output=True, text=True,
    )

    merge_worktree(repo, branch)

    # MERGE_HEAD must not exist (repo not in mid-merge state)
    merge_head = repo / ".git" / "MERGE_HEAD"
    assert not merge_head.exists(), "repo must not be left in mid-merge state"


# ---------------------------------------------------------------------------
# remove_worktree
# ---------------------------------------------------------------------------

def test_remove_worktree_disappears_from_list(tmp_path):
    repo = _init_repo(tmp_path)
    wt_path, branch = create_worktree(repo, "rmtest")
    remove_worktree(repo, wt_path, branch)
    listing = _worktree_list(repo)
    assert str(wt_path) not in listing, "removed worktree must not appear in `git worktree list`"


def test_remove_worktree_path_gone(tmp_path):
    repo = _init_repo(tmp_path)
    wt_path, branch = create_worktree(repo, "pathgone")
    remove_worktree(repo, wt_path, branch)
    assert not Path(wt_path).exists(), "worktree directory must be deleted"


def test_remove_worktree_branch_deleted_by_default(tmp_path):
    repo = _init_repo(tmp_path)
    wt_path, branch = create_worktree(repo, "brdel")
    remove_worktree(repo, wt_path, branch, delete_branch=True)
    result = subprocess.run(
        ["git", "-C", str(repo), "branch"],
        check=True, capture_output=True, text=True,
    )
    assert branch not in result.stdout, "branch must be deleted when delete_branch=True"


def test_remove_worktree_branch_kept_when_requested(tmp_path):
    repo = _init_repo(tmp_path)
    wt_path, branch = create_worktree(repo, "brkeep")
    remove_worktree(repo, wt_path, branch, delete_branch=False)
    result = subprocess.run(
        ["git", "-C", str(repo), "branch"],
        check=True, capture_output=True, text=True,
    )
    assert branch in result.stdout, "branch must survive when delete_branch=False"
