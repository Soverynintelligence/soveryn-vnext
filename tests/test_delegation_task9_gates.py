"""Task-9 enable-gate safety: acceptance runner, merge branch-guard, recovery.

These are the non-tool-isolation guards that must hold before the delegation
worker turns on.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from soveryn.platform.delegation.acceptance import run_acceptance_in_worktree
from soveryn.platform.delegation.worktree import merge_worktree, current_branch
from soveryn.platform.delegation.worker import _recover_stale_executing


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, capture_output=True, text=True,
    ).stdout


# ─── Acceptance runner ────────────────────────────────────────────────────────

@pytest.fixture
def wt(tmp_path):
    root = tmp_path / "wt"
    (root / "tests").mkdir(parents=True)
    return root


def test_acceptance_green(wt):
    (wt / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    passed, output = run_acceptance_in_worktree(str(wt), "python -m pytest tests/test_ok.py -q")
    assert passed is True
    assert "passed" in output


def test_acceptance_red(wt):
    (wt / "tests" / "test_bad.py").write_text("def test_bad():\n    assert False\n")
    passed, output = run_acceptance_in_worktree(str(wt), "python -m pytest tests/test_bad.py -q")
    assert passed is False


def test_acceptance_respects_shlex_quoting(wt):
    # argv[1] must arrive as the single token "a b" — shlex keeps it whole;
    # naive str.split() would shatter it into '"a' and 'b"' and the exit code
    # would flip. This is the concrete shlex-vs-split regression guard.
    cmd = 'python -c \'import sys; sys.exit(0 if sys.argv[1] == "a b" else 3)\' "a b"'
    passed, _ = run_acceptance_in_worktree(str(wt), cmd)
    assert passed is True


def test_acceptance_bad_quotes_is_clean_false(wt):
    passed, output = run_acceptance_in_worktree(str(wt), 'python -c "unterminated')
    assert passed is False
    assert "could not parse" in output


# ─── Merge branch-guard ───────────────────────────────────────────────────────

@pytest.fixture
def repo_with_task_branch(tmp_path):
    """A repo on 'main' with a mergeable 'task/x' branch that adds a file."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "a@b.test")
    _git(root, "config", "user.name", "AB")
    _git(root, "checkout", "-q", "-b", "main")
    (root / "base.txt").write_text("base\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "checkout", "-q", "-b", "task/x")
    (root / "feature.txt").write_text("feature\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "feature")
    _git(root, "checkout", "-q", "main")
    return root


def test_merge_succeeds_when_on_main(repo_with_task_branch):
    ok, _ = merge_worktree(repo_with_task_branch, "task/x", into="main")
    assert ok is True
    assert (repo_with_task_branch / "feature.txt").exists()


def test_merge_refused_when_not_on_main(repo_with_task_branch):
    _git(repo_with_task_branch, "checkout", "-q", "-b", "some-other-branch")
    ok, msg = merge_worktree(repo_with_task_branch, "task/x", into="main")
    assert ok is False
    assert "not the integration branch" in msg
    # Nothing merged — the feature file did not land on the stray branch.
    assert not (repo_with_task_branch / "feature.txt").exists()


def test_current_branch_reports_main(repo_with_task_branch):
    assert current_branch(repo_with_task_branch) == "main"


# ─── Stranded-executing recovery ──────────────────────────────────────────────

class _FakeTask:
    def __init__(self, tid, status):
        self.id = tid
        self.status = status
        self.worktree_path = f"/tmp/wt/{tid}"


class _FakeStore:
    def __init__(self, tasks):
        self._tasks = {t.id: t for t in tasks}
        self.status_calls = []

    def list_tasks(self, *, status=None):
        return tuple(t for t in self._tasks.values() if status is None or t.status == status)

    def set_status(self, task_id, status):
        self.status_calls.append((task_id, status))
        self._tasks[task_id].status = status
        return True


def test_recover_marks_executing_failed():
    store = _FakeStore([
        _FakeTask("a", "executing"),
        _FakeTask("b", "dispatched"),
        _FakeTask("c", "executing"),
    ])
    n = _recover_stale_executing(store)
    assert n == 2
    assert ("a", "failed") in store.status_calls
    assert ("c", "failed") in store.status_calls
    # dispatched task untouched
    assert store._tasks["b"].status == "dispatched"


def test_recover_noop_when_none_executing():
    store = _FakeStore([_FakeTask("a", "dispatched")])
    assert _recover_stale_executing(store) == 0
    assert store.status_calls == []
