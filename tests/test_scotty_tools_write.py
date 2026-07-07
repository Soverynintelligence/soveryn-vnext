"""Tests for Scotty's write tools: edit_file + run_command + git_restore_file.

These tests touch the real vnext working tree (creating scratch files
under tests/_test_* and restoring afterwards). They are NOT isolated
from git; they use try/finally to keep the repo clean.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from soveryn.agents.scotty.tools import (
    SCOTTY_PROJECT_ROOT,
    build_edit_file_tool,
    build_git_restore_file_tool,
    build_run_command_tool,
)
from soveryn.agents.scotty.tools.run_command import ALLOWED_EXECUTABLES
from soveryn.platform.tools.registry import ToolArgError


# ─── edit_file ──────────────────────────────────────────────────────────────

@pytest.fixture
def scratch_file():
    """A scratch file inside the repo for edit tests; cleaned up after."""
    path = SCOTTY_PROJECT_ROOT / "tests" / "_test_scotty_edit_scratch.txt"
    path.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    yield path
    if path.exists():
        path.unlink()


def test_edit_file_replaces_unique_match(scratch_file):
    tool = build_edit_file_tool(owner_agent="scotty")
    result = tool.handler({
        "path": str(scratch_file),
        "old_string": "beta",
        "new_string": "BETA",
    })
    assert result["edited"] is True
    assert result["occurrences_replaced"] == 1
    assert scratch_file.read_text() == "alpha\nBETA\ngamma\n"


def test_edit_file_refuses_ambiguous_match(scratch_file):
    """If old_string appears more than once, refuse without writing."""
    scratch_file.write_text("dup\ndup\n", encoding="utf-8")
    tool = build_edit_file_tool(owner_agent="scotty")
    with pytest.raises(ToolArgError, match="matches 2 locations"):
        tool.handler({
            "path": str(scratch_file),
            "old_string": "dup",
            "new_string": "ONCE",
        })
    # File unchanged
    assert scratch_file.read_text() == "dup\ndup\n"


def test_edit_file_refuses_missing_match(scratch_file):
    tool = build_edit_file_tool(owner_agent="scotty")
    with pytest.raises(ToolArgError, match="not found"):
        tool.handler({
            "path": str(scratch_file),
            "old_string": "nonexistent text",
            "new_string": "replacement",
        })
    assert scratch_file.read_text() == "alpha\nbeta\ngamma\n"


def test_edit_file_refuses_identical_strings(scratch_file):
    tool = build_edit_file_tool(owner_agent="scotty")
    with pytest.raises(ToolArgError, match="identical"):
        tool.handler({
            "path": str(scratch_file),
            "old_string": "beta",
            "new_string": "beta",
        })


def test_edit_file_rejects_path_outside_root():
    tool = build_edit_file_tool(owner_agent="scotty")
    with pytest.raises(ToolArgError):
        tool.handler({
            "path": "/etc/hosts",
            "old_string": "localhost",
            "new_string": "x",
        })


def test_edit_file_rejects_missing_file():
    tool = build_edit_file_tool(owner_agent="scotty")
    with pytest.raises(ToolArgError):
        tool.handler({
            "path": "tests/_does_not_exist.txt",
            "old_string": "x",
            "new_string": "y",
        })


def test_edit_file_rejects_empty_old_string(scratch_file):
    tool = build_edit_file_tool(owner_agent="scotty")
    with pytest.raises(ToolArgError, match="old_string"):
        tool.handler({
            "path": str(scratch_file),
            "old_string": "",
            "new_string": "x",
        })


def test_edit_file_can_delete_with_empty_new_string(scratch_file):
    """new_string="" is allowed — it's a delete-substring operation."""
    tool = build_edit_file_tool(owner_agent="scotty")
    result = tool.handler({
        "path": str(scratch_file),
        "old_string": "beta\n",
        "new_string": "",
    })
    assert result["edited"] is True
    assert scratch_file.read_text() == "alpha\ngamma\n"


# ─── run_command: argument + allowlist enforcement ──────────────────────────

def test_run_command_rejects_executable_not_in_allowlist():
    tool = build_run_command_tool(owner_agent="scotty")
    with pytest.raises(ToolArgError, match="not in allow-list"):
        tool.handler({"executable": "rm", "args": ["-rf", "/"]})
    with pytest.raises(ToolArgError, match="not in allow-list"):
        tool.handler({"executable": "bash", "args": ["-c", "echo x"]})
    with pytest.raises(ToolArgError, match="not in allow-list"):
        tool.handler({"executable": "curl", "args": ["http://x"]})


def test_run_command_rejects_args_not_a_list():
    tool = build_run_command_tool(owner_agent="scotty")
    with pytest.raises(ToolArgError, match="list"):
        tool.handler({"executable": "git", "args": "log"})
    with pytest.raises(ToolArgError, match="list"):
        tool.handler({"executable": "git", "args": None})


def test_run_command_rejects_non_string_args():
    tool = build_run_command_tool(owner_agent="scotty")
    with pytest.raises(ToolArgError, match="string"):
        tool.handler({"executable": "git", "args": ["log", 123]})


def test_run_command_rejects_python_dash_c():
    """`python -c "..."` would smuggle arbitrary code as an arg."""
    tool = build_run_command_tool(owner_agent="scotty")
    with pytest.raises(ToolArgError, match="-c"):
        tool.handler({"executable": "python", "args": ["-c", "import os; os.system('echo x')"]})


def test_run_command_rejects_disallowed_git_subcommand():
    """git push / git reset / git clean must be refused even though 'git' is allow-listed."""
    tool = build_run_command_tool(owner_agent="scotty")
    for sub in ("push", "reset", "clean", "checkout", "rm", "mv"):
        with pytest.raises(ToolArgError, match="not allowed"):
            tool.handler({"executable": "git", "args": [sub]})


def test_run_command_rejects_bad_timeout():
    tool = build_run_command_tool(owner_agent="scotty")
    with pytest.raises(ToolArgError):
        tool.handler({"executable": "git", "args": ["log", "-1"], "timeout": 0})
    with pytest.raises(ToolArgError):
        tool.handler({"executable": "git", "args": ["log", "-1"], "timeout": 99999})


def test_run_command_allows_git_read_only_subcommand():
    """git log -1 --oneline should succeed against the real vnext repo."""
    tool = build_run_command_tool(owner_agent="scotty")
    result = tool.handler({"executable": "git", "args": ["log", "-1", "--oneline"]})
    assert result["timed_out"] is False
    assert result["returncode"] == 0
    assert result["stdout_tail"]  # last commit message present


def test_run_command_allows_python_module_invocation():
    """`python --version` should succeed."""
    tool = build_run_command_tool(owner_agent="scotty")
    result = tool.handler({"executable": "python", "args": ["--version"]})
    assert result["timed_out"] is False
    assert result["returncode"] == 0
    # Python emits version to stdout on 3.4+; stderr historically — accept either.
    combined = (result["stdout_tail"] + result["stderr_tail"]).lower()
    assert "python" in combined


# ─── git_restore_file ───────────────────────────────────────────────────────

FIXTURE_RESTORE_TARGET = (
    SCOTTY_PROJECT_ROOT / "tests" / "fixtures" / "scotty_restore_target.txt"
)
FIXTURE_RESTORE_TARGET_ORIGINAL = (
    "original content for scotty restore tests — do not edit manually\n"
)


@pytest.fixture
def tracked_scratch_file():
    """A real tracked fixture file under tests/fixtures/. Tests modify it
    in-flight; the fixture's teardown uses `git checkout` to revert any
    leftover dirt. Critically, NO new commits are created per test run —
    the file is committed once in the repo and reused forever.
    """
    rel = str(FIXTURE_RESTORE_TARGET.relative_to(SCOTTY_PROJECT_ROOT))
    yield FIXTURE_RESTORE_TARGET
    # Teardown: ensure the working copy matches HEAD, regardless of how the
    # test left it. Also unstage anything the test staged.
    subprocess.run(
        ["git", "reset", "HEAD", "--", rel],
        cwd=SCOTTY_PROJECT_ROOT, check=False, capture_output=True,
    )
    subprocess.run(
        ["git", "checkout", "HEAD", "--", rel],
        cwd=SCOTTY_PROJECT_ROOT, check=False, capture_output=True,
    )


def test_git_restore_file_reverts_unstaged_changes(tracked_scratch_file):
    """Dirty the file (unstaged), then restore — content reverts to HEAD."""
    tracked_scratch_file.write_text("dirty content\n", encoding="utf-8")
    assert tracked_scratch_file.read_text() == "dirty content\n"
    tool = build_git_restore_file_tool(owner_agent="scotty")
    result = tool.handler({"path": str(tracked_scratch_file)})
    assert result["restored"] is True
    assert tracked_scratch_file.read_text() == FIXTURE_RESTORE_TARGET_ORIGINAL


def test_git_restore_file_refuses_with_staged_changes(tracked_scratch_file):
    """Staged changes for the same path must block restore."""
    tracked_scratch_file.write_text("staged content\n", encoding="utf-8")
    rel = str(tracked_scratch_file.relative_to(SCOTTY_PROJECT_ROOT))
    subprocess.run(
        ["git", "add", rel],
        cwd=SCOTTY_PROJECT_ROOT, check=True, capture_output=True,
    )
    tool = build_git_restore_file_tool(owner_agent="scotty")
    with pytest.raises(ToolArgError, match="staged changes"):
        tool.handler({"path": str(tracked_scratch_file)})
    # File unchanged — staged version still present in working tree
    assert tracked_scratch_file.read_text() == "staged content\n"
    # Fixture teardown unstages + checks out HEAD; no inline cleanup needed.


def test_git_restore_file_refuses_untracked_file():
    """Untracked file → ls-files --error-unmatch fails → ToolArgError."""
    untracked = SCOTTY_PROJECT_ROOT / "tests" / "_test_scotty_untracked.txt"
    untracked.write_text("never tracked\n", encoding="utf-8")
    try:
        tool = build_git_restore_file_tool(owner_agent="scotty")
        with pytest.raises(ToolArgError, match="not a tracked file"):
            tool.handler({"path": str(untracked)})
    finally:
        untracked.unlink()


def test_git_restore_file_rejects_path_outside_root():
    tool = build_git_restore_file_tool(owner_agent="scotty")
    with pytest.raises(ToolArgError):
        tool.handler({"path": "/etc/hosts"})


# ─── ALLOWED_EXECUTABLES sanity ─────────────────────────────────────────────

def test_allowed_executables_contains_expected_set():
    """If anyone adds an entry, the change has to be reviewed against this list."""
    assert set(ALLOWED_EXECUTABLES) == {
        "python", "pytest", "ruff", "black", "mypy", "git",
    }


# ─── run_command: git config is read-only (Task-9 hardening) ─────────────────

def test_run_command_git_config_write_rejected():
    from soveryn.agents.scotty.tools import build_run_command_tool
    from soveryn.platform.tools.registry import ToolArgError
    tool = build_run_command_tool(owner_agent="scotty")
    with pytest.raises(ToolArgError):
        tool.handler({"executable": "git", "args": ["config", "user.name", "attacker"]})


def test_run_command_git_config_read_allowed():
    from soveryn.agents.scotty.tools import build_run_command_tool
    tool = build_run_command_tool(owner_agent="scotty")
    out = tool.handler({"executable": "git", "args": ["config", "--get", "core.bare"]})
    # --get is permitted; returncode may be non-zero if the key is unset, but the
    # guard must not have rejected it (we get a structured result, not a raise).
    assert "returncode" in out
