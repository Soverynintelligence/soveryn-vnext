"""The delegation Scotty-runner must build a tool registry whose write/exec
tools are pinned to the worktree, not the live repo.

This closes the Task-8 stub: previously edit_file/run_command/git_*/run_pytest
used SCOTTY_PROJECT_ROOT even inside a delegation run. Here we build the
registry against a tmp worktree and prove the write path lands there.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from soveryn.platform.delegation.scotty_runner import build_worktree_tool_registry
from soveryn.agents.scotty.tools.paths import SCOTTY_PROJECT_ROOT


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, capture_output=True, text=True,
    ).stdout


@pytest.fixture
def wt(tmp_path):
    root = tmp_path / "wt"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "s@x.test")
    _git(root, "config", "user.name", "S")
    _git(root, "checkout", "-q", "-b", "task/x")
    (root / "mod.py").write_text("V = 1\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root


def _tool(reg, name):
    for spec in reg.iter_tools_for_agent("scotty"):
        if spec.name == name:
            return spec
    raise AssertionError(f"tool {name!r} not registered")


def test_registry_has_all_scotty_tools(wt):
    reg = build_worktree_tool_registry(wt)
    names = {s.name for s in reg.iter_tools_for_agent("scotty")}
    assert {
        "read_file", "list_directory", "edit_file", "run_command",
        "git_status", "git_diff", "git_restore_file", "run_pytest",
    } <= names


def test_edit_file_from_registry_writes_to_worktree(wt):
    reg = build_worktree_tool_registry(wt)
    out = _tool(reg, "edit_file").handler(
        {"path": "mod.py", "old_string": "V = 1", "new_string": "V = 2"}
    )
    assert (wt / "mod.py").read_text() == "V = 2\n"
    assert str(wt) in out["path"]
    assert str(SCOTTY_PROJECT_ROOT) not in out["path"]


def test_git_status_from_registry_reads_worktree(wt):
    (wt / "mod.py").write_text("V = 9\n")
    reg = build_worktree_tool_registry(wt)
    out = _tool(reg, "git_status").handler({})
    assert out["clean"] is False
    assert str(wt.resolve()) == out["cwd"]
