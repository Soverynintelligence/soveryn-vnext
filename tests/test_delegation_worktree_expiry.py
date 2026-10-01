"""in_review worktree expiry — disk hygiene, not a review timeout (hole #4)."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from soveryn.platform.delegation.engine import _expire_in_review_worktrees


@dataclass
class FakeTask:
    id: str
    worktree_path: str | None
    branch: str | None
    updated_at: str


@dataclass
class FakeStore:
    tasks: list = field(default_factory=list)
    cleared: list = field(default_factory=list)

    def list_tasks(self, *, status=None):
        return tuple(self.tasks)

    def clear_worktree(self, task_id):
        self.cleared.append(task_id)
        return True


def _removed(targets: list):
    calls = []

    def remove(repo_root, wt, branch):
        calls.append(wt)
        Path(wt).rmdir()

    remove.calls = calls
    return remove


def test_old_in_review_worktree_expires_branch_kept(tmp_path):
    old_dir = tmp_path / "wt-old"
    old_dir.mkdir()
    store = FakeStore(tasks=[FakeTask(
        id="t1", worktree_path=str(old_dir), branch="task/t1",
        updated_at=(datetime.now() - timedelta(days=8)).isoformat(),
    )])
    remove = _removed([])
    expired = _expire_in_review_worktrees(store, remove, str(tmp_path), now=time.time())
    assert expired == 1
    assert not old_dir.exists()
    assert store.cleared == ["t1"]


def test_fresh_in_review_worktree_is_untouched(tmp_path):
    fresh_dir = tmp_path / "wt-fresh"
    fresh_dir.mkdir()
    store = FakeStore(tasks=[FakeTask(
        id="t2", worktree_path=str(fresh_dir), branch="task/t2",
        updated_at=datetime.now().isoformat(),
    )])
    remove = _removed([])
    assert _expire_in_review_worktrees(store, remove, str(tmp_path), now=time.time()) == 0
    assert fresh_dir.exists() and store.cleared == []


def test_missing_dir_and_bad_dates_skip_cleanly(tmp_path):
    store = FakeStore(tasks=[
        FakeTask(id="t3", worktree_path=str(tmp_path / "gone"), branch="task/t3",
                 updated_at=(datetime.now() - timedelta(days=30)).isoformat()),
        FakeTask(id="t4", worktree_path=None, branch=None,
                 updated_at=(datetime.now() - timedelta(days=30)).isoformat()),
        FakeTask(id="t5", worktree_path=str(tmp_path / "x"), branch="task/t5",
                 updated_at="not-a-date"),
    ])
    remove = _removed([])
    assert _expire_in_review_worktrees(store, remove, str(tmp_path), now=time.time()) == 0
