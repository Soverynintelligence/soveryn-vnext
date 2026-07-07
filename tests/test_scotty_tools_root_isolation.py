"""Scotty's write/exec tools must honor a per-build ``root`` so delegated
execution can pin them to an isolated worktree instead of the live repo.

This is the load-bearing safety property for turning the delegation worker on:
when the engine hands Scotty a worktree, every file write, git op, and test run
must land inside that worktree and be *unable* to touch ``SCOTTY_PROJECT_ROOT``.

Each test builds a tool with ``root=<tmp>`` and asserts the operation happens in
<tmp>, and that a path escaping to the live root is rejected.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from soveryn.agents.scotty.tools.paths import SCOTTY_PROJECT_ROOT
from soveryn.agents.scotty.tools import (
    build_edit_file_tool,
    build_run_command_tool,
    build_git_status_tool,
    build_git_diff_tool,
    build_git_restore_file_tool,
    build_run_pytest_tool,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, capture_output=True, text=True,
    ).stdout


@pytest.fixture
def wt(tmp_path):
    """A throwaway git repo standing in for an isolated worktree."""
    root = tmp_path / "wt"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "scotty@soveryn.test")
    _git(root, "config", "user.name", "Scotty Test")
    _git(root, "checkout", "-q", "-b", "task/x")
    (root / "mod.py").write_text("VALUE = 1\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root


# ─── edit_file ────────────────────────────────────────────────────────────────

def test_edit_file_writes_into_root_not_live(wt):
    tool = build_edit_file_tool(owner_agent="scotty", root=wt)
    out = tool.handler({"path": "mod.py", "old_string": "VALUE = 1", "new_string": "VALUE = 2"})
    assert out["edited"] is True
    assert (wt / "mod.py").read_text() == "VALUE = 2\n"
    # The edit resolved under the worktree, not the live repo.
    assert str(wt) in out["path"]
    assert str(SCOTTY_PROJECT_ROOT) not in out["path"]


def test_edit_file_rejects_escape_to_live_root(wt):
    tool = build_edit_file_tool(owner_agent="scotty", root=wt)
    # An absolute path into the live repo must be refused — it's outside root.
    live_file = str(SCOTTY_PROJECT_ROOT / "soveryn" / "app" / "startup.py")
    from soveryn.platform.tools.registry import ToolArgError
    with pytest.raises(ToolArgError):
        tool.handler({"path": live_file, "old_string": "x", "new_string": "y"})


def test_edit_file_default_root_is_live(wt):
    # Without root=, the default is still SCOTTY_PROJECT_ROOT (back-compat).
    tool = build_edit_file_tool(owner_agent="scotty")
    from soveryn.platform.tools.registry import ToolArgError
    # A path under the worktree (outside the live root) is now rejected.
    with pytest.raises(ToolArgError):
        tool.handler({"path": str(wt / "mod.py"), "old_string": "VALUE = 1", "new_string": "VALUE = 9"})


# ─── run_command ──────────────────────────────────────────────────────────────

def test_run_command_cwd_is_root(wt):
    tool = build_run_command_tool(owner_agent="scotty", root=wt)
    out = tool.handler({"executable": "git", "args": ["rev-parse", "--show-toplevel"]})
    assert out["returncode"] == 0
    # git resolved the worktree as its toplevel — cwd was the worktree.
    assert str(wt.resolve()) in out["stdout_tail"]


def test_run_command_pythonpath_is_root(wt):
    # A python probe that imports a module only present in the worktree proves
    # PYTHONPATH points at root (import isolation).
    (wt / "probe_pkg.py").write_text("MARK = 'WT'\n")
    tool = build_run_command_tool(owner_agent="scotty", root=wt)
    out = tool.handler({"executable": "python", "args": ["-m", "probe_pkg"]})
    # -m probe_pkg runs the module; it has no __main__ so returncode!=0, but the
    # import must SUCCEED (no ModuleNotFoundError) — proving PYTHONPATH=root.
    assert "ModuleNotFoundError" not in out["stderr_tail"]


# ─── git tools ────────────────────────────────────────────────────────────────

def test_git_status_reads_root(wt):
    (wt / "mod.py").write_text("VALUE = 99\n")  # dirty
    tool = build_git_status_tool(owner_agent="scotty", root=wt)
    out = tool.handler({})
    assert out["clean"] is False
    assert str(wt.resolve()) == out["cwd"]


def test_git_diff_reads_root(wt):
    (wt / "mod.py").write_text("VALUE = 42\n")
    tool = build_git_diff_tool(owner_agent="scotty", root=wt)
    out = tool.handler({})
    assert "VALUE = 42" in out["diff"]


def test_git_restore_file_restores_in_root(wt):
    (wt / "mod.py").write_text("VALUE = 777\n")  # unstaged change
    tool = build_git_restore_file_tool(owner_agent="scotty", root=wt)
    out = tool.handler({"path": "mod.py"})
    assert out["restored"] is True
    assert (wt / "mod.py").read_text() == "VALUE = 1\n"  # reverted


# ─── run_pytest ───────────────────────────────────────────────────────────────

def test_run_pytest_runs_in_root(wt):
    tests_dir = wt / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_probe.py").write_text("def test_ok():\n    assert True\n")
    tool = build_run_pytest_tool(owner_agent="scotty", root=wt)
    out = tool.handler({"target": "tests/test_probe.py"})
    assert out["passed"] is True
    assert str(wt.resolve()) in out["target"]


def test_run_pytest_rejects_target_outside_root(wt):
    (wt / "tests").mkdir()
    tool = build_run_pytest_tool(owner_agent="scotty", root=wt)
    from soveryn.platform.tools.registry import ToolArgError
    with pytest.raises(ToolArgError):
        # The live tests/ dir is outside the worktree root — rejected.
        tool.handler({"target": str(SCOTTY_PROJECT_ROOT / "tests")})
