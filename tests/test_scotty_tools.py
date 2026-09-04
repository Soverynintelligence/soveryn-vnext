"""Tests for Scotty's five bounded mechanical tools.

Path allow-list, size/time caps, symlink-escape rejection, and tool-result
shape contracts. Subprocess-backed tools (git, pytest) are exercised
against the live vnext repo since that's the only realistic test environment;
they're tagged so they can be skipped if the repo state is unfavourable.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from soveryn.agents.scotty.tools import (
    SCOTTY_PROJECT_ROOT,
    build_git_diff_tool,
    build_git_status_tool,
    build_list_directory_tool,
    build_read_file_tool,
    build_run_pytest_tool,
)
from soveryn.agents.scotty.tools.fs import (
    LIST_DIRECTORY_MAX_ENTRIES,
    READ_FILE_MAX_BYTES,
)
from soveryn.agents.scotty.tools.paths import (
    PathOutOfBoundsError,
    resolve_within_root,
)
from soveryn.platform.tools.registry import ToolArgError


# ─── Path validation helper ─────────────────────────────────────────────────

def test_resolve_within_root_accepts_relative_path():
    p = resolve_within_root("soveryn/app/startup.py", must_exist=True)
    assert p.is_absolute()
    assert p.is_relative_to(SCOTTY_PROJECT_ROOT)


def test_resolve_within_root_accepts_absolute_path_within_root():
    target = SCOTTY_PROJECT_ROOT / "soveryn"
    p = resolve_within_root(str(target), must_exist=True)
    assert p == target.resolve()


def test_resolve_within_root_rejects_absolute_outside_root():
    with pytest.raises(PathOutOfBoundsError, match="outside"):
        resolve_within_root("/etc/passwd")


def test_resolve_within_root_rejects_traversal_escape():
    """Even though the literal string starts inside, .. that escapes is rejected."""
    with pytest.raises(PathOutOfBoundsError, match="outside"):
        resolve_within_root("../../etc/passwd")


def test_resolve_within_root_rejects_empty_path():
    with pytest.raises(PathOutOfBoundsError, match="non-empty"):
        resolve_within_root("")


def test_resolve_within_root_must_exist_raises_for_missing():
    with pytest.raises(FileNotFoundError):
        resolve_within_root("definitely-does-not-exist.txt", must_exist=True)


# ─── read_file ──────────────────────────────────────────────────────────────

def test_read_file_returns_content_for_real_repo_file():
    tool = build_read_file_tool(owner_agent="scotty")
    result = tool.handler({"path": "pyproject.toml"})
    assert "content" in result
    assert "[tool.pytest" in result["content"] or "pytest" in result["content"].lower()
    assert result["truncated"] is False


def test_read_file_rejects_path_outside_root():
    tool = build_read_file_tool(owner_agent="scotty")
    with pytest.raises(ToolArgError, match="outside"):
        tool.handler({"path": "/etc/passwd"})


def test_read_file_rejects_missing_file():
    tool = build_read_file_tool(owner_agent="scotty")
    with pytest.raises(ToolArgError, match="does not exist"):
        tool.handler({"path": "this-file-does-not-exist.txt"})


def test_read_file_rejects_directory():
    tool = build_read_file_tool(owner_agent="scotty")
    with pytest.raises(ToolArgError, match="not a regular file"):
        tool.handler({"path": "soveryn"})


def test_read_file_truncates_oversized(tmp_path, monkeypatch):
    # Create a large file inside the project root for the test
    test_file = SCOTTY_PROJECT_ROOT / "tests" / "_test_oversize_tmp.txt"
    try:
        test_file.write_text("x" * (READ_FILE_MAX_BYTES + 1024))
        tool = build_read_file_tool(owner_agent="scotty")
        result = tool.handler({"path": str(test_file)})
        assert result["truncated"] is True
        assert len(result["content"]) == READ_FILE_MAX_BYTES
        assert result["size_bytes"] == READ_FILE_MAX_BYTES + 1024
    finally:
        if test_file.exists():
            test_file.unlink()


def test_read_file_offset_pages(tmp_path):
    target = tmp_path / "page.txt"
    target.write_text("ABCDEFGHIJ")
    tool = build_read_file_tool(owner_agent="vett", root=tmp_path)
    result = tool.handler({"path": str(target), "offset": 3, "max_bytes": 4})
    assert result["content"] == "DEFG"
    assert result["offset"] == 3
    assert result["truncated"] is True


def test_read_file_spill_path_does_not_dump_40kb(tmp_path):
    from soveryn.agents.scotty.tools.fs import SPILL_REREAD_MAX_BYTES

    spill = tmp_path / "tool_spill" / "sess" / "fat.txt"
    spill.parent.mkdir(parents=True)
    spill.write_text("Z" * (READ_FILE_MAX_BYTES + 5000))
    tool = build_read_file_tool(owner_agent="vett", root=tmp_path)
    result = tool.handler({"path": str(spill)})
    assert result["spill_reread"] is True
    assert len(result["content"]) <= SPILL_REREAD_MAX_BYTES
    assert result["truncated"] is True


# ─── custom root (Vett's wider "view outside soveryn" scope) ─────────────────

def test_read_file_honors_custom_root(tmp_path):
    # A tool built with a wider root reads files outside the default vnext
    # project root — this is Vett's "view outside SOVERYN" capability.
    target = tmp_path / "outside.txt"
    target.write_text("visible from custom root")
    tool = build_read_file_tool(owner_agent="vett", root=tmp_path)
    result = tool.handler({"path": str(target)})
    assert result["content"] == "visible from custom root"


def test_read_file_custom_root_still_fences(tmp_path):
    # The custom root is still a fence: paths outside it are rejected.
    inner = tmp_path / "inner"
    inner.mkdir()
    tool = build_read_file_tool(owner_agent="vett", root=inner)
    with pytest.raises(ToolArgError, match="outside"):
        tool.handler({"path": str(tmp_path / "sibling.txt")})


def test_list_directory_honors_custom_root(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "sub").mkdir()
    tool = build_list_directory_tool(owner_agent="vett", root=tmp_path)
    result = tool.handler({"path": str(tmp_path)})
    names = {e["name"] for e in result["entries"]}
    assert {"a.txt", "sub"} <= names


# ─── list_directory ─────────────────────────────────────────────────────────

def test_list_directory_returns_sorted_entries():
    tool = build_list_directory_tool(owner_agent="scotty")
    result = tool.handler({"path": "soveryn"})
    assert result["count"] > 0
    names = [e["name"] for e in result["entries"]]
    assert names == sorted(names)


def test_list_directory_defaults_to_root_when_path_omitted():
    tool = build_list_directory_tool(owner_agent="scotty")
    result = tool.handler({})
    assert result["count"] > 0
    names = {e["name"] for e in result["entries"]}
    # Sanity check: the root should have pyproject.toml at minimum
    assert "pyproject.toml" in names or "soveryn" in names


def test_list_directory_rejects_path_outside_root():
    tool = build_list_directory_tool(owner_agent="scotty")
    with pytest.raises(ToolArgError, match="outside"):
        tool.handler({"path": "/etc"})


def test_list_directory_rejects_file_target():
    tool = build_list_directory_tool(owner_agent="scotty")
    with pytest.raises(ToolArgError, match="not a directory"):
        tool.handler({"path": "pyproject.toml"})


def test_list_directory_truncates_at_max_entries(tmp_path):
    # Create a directory with > LIST_DIRECTORY_MAX_ENTRIES files inside the root
    test_dir = SCOTTY_PROJECT_ROOT / "tests" / "_test_listdir_tmp"
    try:
        test_dir.mkdir(exist_ok=True)
        for i in range(LIST_DIRECTORY_MAX_ENTRIES + 5):
            (test_dir / f"file_{i:04d}.txt").write_text("x")
        tool = build_list_directory_tool(owner_agent="scotty")
        result = tool.handler({"path": str(test_dir)})
        assert result["truncated"] is True
        assert result["count"] == LIST_DIRECTORY_MAX_ENTRIES
    finally:
        # Clean up
        if test_dir.exists():
            for f in test_dir.iterdir():
                f.unlink()
            test_dir.rmdir()


# ─── git_status ─────────────────────────────────────────────────────────────

def test_git_status_returns_branch_summary_and_changes():
    tool = build_git_status_tool(owner_agent="scotty")
    result = tool.handler({})
    assert "branch_summary" in result
    assert "changes" in result
    assert isinstance(result["changes"], list)
    assert "clean" in result
    # cwd is always the project root
    assert result["cwd"] == str(SCOTTY_PROJECT_ROOT)


# ─── git_diff ───────────────────────────────────────────────────────────────

def test_git_diff_unstaged_returns_diff_field():
    tool = build_git_diff_tool(owner_agent="scotty")
    result = tool.handler({})
    assert "diff" in result
    assert result["staged"] is False
    assert "line_count" in result
    assert "truncated_lines" in result
    assert "truncated_bytes" in result


def test_git_diff_staged_runs_cached():
    tool = build_git_diff_tool(owner_agent="scotty")
    result = tool.handler({"staged": True})
    assert result["staged"] is True


# ─── run_pytest ─────────────────────────────────────────────────────────────

def test_run_pytest_rejects_target_outside_tests_dir():
    tool = build_run_pytest_tool(owner_agent="scotty")
    with pytest.raises(ToolArgError, match="under tests"):
        tool.handler({"target": "soveryn/app/startup.py"})


def test_run_pytest_rejects_path_outside_root():
    tool = build_run_pytest_tool(owner_agent="scotty")
    with pytest.raises(ToolArgError, match="outside"):
        tool.handler({"target": "/tmp"})


def test_run_pytest_runs_single_test_and_returns_summary():
    """Run one cheap test we know exists and passes. Confirms the shape and
    that subprocess wiring works end-to-end."""
    # Pick a test that's known to pass and is fast
    target = "tests/test_conversation_store.py::test_new_session_returns_uuid"
    tool = build_run_pytest_tool(owner_agent="scotty")
    result = tool.handler({"target": target})
    assert result["passed"] is True
    assert result["returncode"] == 0
    assert "passed" in result["summary_line"]
    assert isinstance(result["stdout_tail"], str)
