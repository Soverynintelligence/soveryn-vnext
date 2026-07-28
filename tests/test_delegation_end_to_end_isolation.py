"""End-to-end delegation isolation proof — the gate for turning the worker on.

Drives the REAL engine (real worktree creation, real diff/commit, real acceptance
runner) with a deterministic stand-in for Scotty that edits through the
worktree-pinned tools. Proves the load-bearing guarantees hold through the whole
chain, with no llama-server:

  1. Scotty's edit lands in the WORKTREE.
  2. The live repo's working tree is BYTE-IDENTICAL afterward (isolation).
  3. Acceptance runs against the WORKTREE's code (import isolation): the test
     imports V, which is 2 only in the worktree — if PYTHONPATH leaked to the
     live tree it would import V=1 and the acceptance would fail.
  4. Green acceptance → task in_review with a captured diff + test output.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from soveryn.platform.delegation.store import DelegationStore
from soveryn.platform.delegation.engine import execute_task
from soveryn.platform.delegation.scotty_runner import build_worktree_tool_registry
from soveryn.platform.delegation.acceptance import run_acceptance_in_worktree


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, capture_output=True, text=True,
    ).stdout


@pytest.fixture
def live_repo(tmp_path):
    """A throwaway 'live' repo on main: mod.py (V=1) + a test asserting V==2."""
    root = tmp_path / "live"
    (root / "tests").mkdir(parents=True)
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "a@b.test")
    _git(root, "config", "user.name", "AB")
    (root / "mod.py").write_text("V = 1\n")
    # Acceptance test imports mod.V — passes only when V == 2 (Scotty's edit).
    (root / "tests" / "test_mod.py").write_text(
        "import mod\n\n\ndef test_v():\n    assert mod.V == 2\n"
    )
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base V=1")
    return root


def _tool(reg, name):
    for spec in reg.iter_tools_for_agent("scotty"):
        if spec.name == name:
            return spec
    raise AssertionError(name)


def test_delegation_isolation_end_to_end(live_repo):
    store = DelegationStore(live_repo / "delegation.db")
    task_id = store.create_task(
        dispatched_by="aetheria",
        objective="bump V to 2",
        scope="mod.py",
        acceptance="python -m pytest tests/test_mod.py -q",
    )

    # Deterministic Scotty: edit V=1 → V=2 via the worktree-pinned edit_file.
    def fake_scotty_run(worktree_path, objective, scope, acceptance=""):
        reg = build_worktree_tool_registry(Path(worktree_path))
        _tool(reg, "edit_file").handler(
            {"path": "mod.py", "old_string": "V = 1", "new_string": "V = 2"}
        )
        return "bumped V to 2"

    execute_task(
        task_id,
        store=store,
        repo_root=str(live_repo),
        scotty_run=fake_scotty_run,
        run_acceptance=run_acceptance_in_worktree,
    )

    task = store.get_task(task_id)

    # (4) Green acceptance → in_review with evidence.
    assert task.status == "in_review", f"expected in_review, got {task.status}"
    assert "V = 2" in task.diff
    assert "passed" in task.test_output

    # (2) THE isolation guarantee: the live working tree is untouched.
    assert (live_repo / "mod.py").read_text() == "V = 1\n"

    # (1) The change lives on the task branch, not on main.
    main_mod = _git(live_repo, "show", "main:mod.py")
    assert main_mod == "V = 1\n"
    branch_mod = _git(live_repo, "show", f"task/{task_id}:mod.py")
    assert branch_mod == "V = 2\n"


def test_delegation_red_acceptance_fails_and_cleans_up(live_repo):
    """A Scotty that does NOT make the test pass → failed, live tree untouched."""
    store = DelegationStore(live_repo / "delegation.db")
    task_id = store.create_task(
        dispatched_by="aetheria",
        objective="do nothing useful",
        scope="mod.py",
        acceptance="python -m pytest tests/test_mod.py -q",
    )

    def lazy_scotty_run(worktree_path, objective, scope):
        return "did nothing"

    execute_task(
        task_id,
        store=store,
        repo_root=str(live_repo),
        scotty_run=lazy_scotty_run,
        run_acceptance=run_acceptance_in_worktree,
    )

    task = store.get_task(task_id)
    assert task.status == "failed"
    assert (live_repo / "mod.py").read_text() == "V = 1\n"
