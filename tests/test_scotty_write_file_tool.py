"""write_file — the tool Scotty was missing.

Root cause of the 8/8 delegation failures (2026-07-22): every delegated task was
"implement a module", i.e. CREATE new files, but Scotty had no tool that could
create one. ``edit_file`` requires ``old_string`` and refuses non-existent paths
by design; his workaround, ``run_command python -c``, is blocked by the
arbitrary-code guard. He burned his tool-round budget every time and produced an
empty worktree. He even said so in round 4: "The edit_file tool requires the file
to already exist."

These tests pin the contract: write_file CREATES, edit_file MODIFIES, and neither
does the other's job.
"""
from __future__ import annotations

import pytest

from soveryn.agents.scotty.tools import build_write_file_tool
from soveryn.platform.tools.registry import ToolArgError


def _call(tool, **args):
    return tool.handler(dict(args))


def test_creates_a_new_file(tmp_path):
    tool = build_write_file_tool(owner_agent="scotty", root=tmp_path)
    result = _call(tool, path="hello.py", content="print('hi')\n")
    target = tmp_path / "hello.py"
    assert target.exists()
    assert target.read_text() == "print('hi')\n"
    assert result["created"] is True


def test_creates_parent_directories_within_root(tmp_path):
    """Delegated tasks scope to things like 'soveryn/pond_builder/' — a package
    that does not exist yet. Without parent creation Scotty still cannot start."""
    tool = build_write_file_tool(owner_agent="scotty", root=tmp_path)
    _call(tool, path="pkg/sub/mod.py", content="x = 1\n")
    assert (tmp_path / "pkg" / "sub" / "mod.py").read_text() == "x = 1\n"


def test_refuses_to_overwrite_existing_file(tmp_path):
    """Create-only. Overwriting is edit_file's job, and silently clobbering a
    file is exactly the failure mode edit_file's uniqueness guard exists to
    prevent — write_file must not reintroduce it."""
    (tmp_path / "exists.py").write_text("original\n")
    tool = build_write_file_tool(owner_agent="scotty", root=tmp_path)
    with pytest.raises(ToolArgError, match="already exists"):
        _call(tool, path="exists.py", content="clobbered\n")
    assert (tmp_path / "exists.py").read_text() == "original\n"


def test_rejects_paths_escaping_root(tmp_path):
    tool = build_write_file_tool(owner_agent="scotty", root=tmp_path)
    with pytest.raises(ToolArgError):
        _call(tool, path="../escaped.py", content="nope\n")
    assert not (tmp_path.parent / "escaped.py").exists()


def test_rejects_empty_path_and_non_string_content(tmp_path):
    tool = build_write_file_tool(owner_agent="scotty", root=tmp_path)
    with pytest.raises(ToolArgError):
        _call(tool, path="", content="x")
    with pytest.raises(ToolArgError):
        _call(tool, path="a.py", content=123)


def test_enforces_size_cap(tmp_path):
    from soveryn.agents.scotty.tools.write import WRITE_FILE_MAX_BYTES
    tool = build_write_file_tool(owner_agent="scotty", root=tmp_path)
    with pytest.raises(ToolArgError, match="cap"):
        _call(tool, path="big.py", content="x" * (WRITE_FILE_MAX_BYTES + 1))
    assert not (tmp_path / "big.py").exists()


def test_registered_for_delegation_worktrees(tmp_path):
    """The delegation registry is the whole point — if write_file isn't pinned
    into the worktree registry, the 8/8 failure repeats."""
    from soveryn.platform.delegation.scotty_runner import build_worktree_tool_registry
    reg = build_worktree_tool_registry(tmp_path)
    names = {spec.name for spec in reg.iter_tools_for_agent("scotty")}
    assert "write_file" in names
    assert "edit_file" in names
