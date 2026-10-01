"""Regression: relative paths in wide-jail file tools anchor to `base`, not `root`.

2026-09-28 ghost-write: the kernel seat's write_file is jailed to $HOME
(root=Path.home(), deliberate — it writes across many house trees), and
resolve_within_root anchored bare relative paths against that root. A
commission task saying `docs/CURRENT_TRUTH.md` created
$HOME/docs/CURRENT_TRUTH.md; the citizen then byte-verified its own ghost
write while the real repo file went untouched, and reported done.

The fix splits fence (root) from anchor (base): bare `docs/...` now lands
in the vnext repo even when the jail is $HOME. Absolute and ~ paths inside
the jail still work. This test reproduces the ghost-write shape end to end
and fails if it ever comes back.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from soveryn.agents.scotty.tools.fs import build_write_file_tool, build_read_file_tool
from soveryn.agents.scotty.tools.paths import resolve_within_root, PathOutOfBoundsError


@pytest.fixture
def split_roots(tmp_path, monkeypatch):
    """Fake house: jail=$HOME(tmp), repo=tmp/soveryn_vnext."""
    home = tmp_path / "home"
    repo = home / "soveryn_vnext"
    (repo / "docs").mkdir(parents=True)
    monkeypatch.setattr(
        "soveryn.agents.scotty.tools.paths.SCOTTY_PROJECT_ROOT", repo
    )
    return home, repo


def test_relative_path_anchors_to_base_not_root(split_roots):
    home, repo = split_roots
    resolved = resolve_within_root(
        "docs/CURRENT_TRUTH.md", root=home, base=repo
    )
    assert resolved == repo / "docs" / "CURRENT_TRUTH.md"


def test_kernel_write_ghost_write_reproduction(split_roots):
    """The exact 2026-09-28 shape: write `docs/CURRENT_TRUTH.md` with a
    $HOME jail. Must land in the repo; $HOME/docs must NOT be created."""
    home, repo = split_roots
    tool = build_write_file_tool(owner_agent="kernel", root=home, base=repo)
    result = tool.handler({"path": "docs/CURRENT_TRUTH.md", "content": "truth body\n"})
    assert result["ok"] is True
    assert (repo / "docs" / "CURRENT_TRUTH.md").read_text() == "truth body\n"
    assert not (home / "docs" / "CURRENT_TRUTH.md").exists()


def test_absolute_and_tilde_paths_still_reach_the_jail(split_roots, monkeypatch):
    """The fence stays $HOME: absolute and ~ paths inside it still write."""
    home, repo = split_roots
    monkeypatch.setenv("HOME", str(home))
    tool = build_write_file_tool(owner_agent="kernel", root=home, base=repo)

    abs_result = tool.handler(
        {"path": str(home / "demos" / "thing.md"), "content": "demo\n"}
    )
    assert abs_result["ok"] is True
    assert (home / "demos" / "thing.md").exists()

    tilde_result = tool.handler({"path": "~/notes/x.md", "content": "n\n"})
    assert tilde_result["ok"] is True
    assert (home / "notes" / "x.md").exists()


def test_base_cannot_escape_the_fence(split_roots, monkeypatch):
    """base widens the anchor, never the fence: traversal outside root dies."""
    home, repo = split_roots
    with pytest.raises(PathOutOfBoundsError):
        resolve_within_root("../../../etc/passwd", root=home, base=repo)
    monkeypatch.setenv("HOME", str(home))
    tool = build_write_file_tool(owner_agent="kernel", root=home, base=repo)
    with pytest.raises(Exception):
        tool.handler({"path": "~/../../etc/passwd", "content": "x"})


def test_kernel_read_with_base_reads_repo_file(split_roots):
    home, repo = split_roots
    (repo / "docs" / "real.md").write_text("real truth\n")
    tool = build_read_file_tool(owner_agent="kernel", root=home, base=repo)
    result = tool.handler({"path": "docs/real.md"})
    assert "real truth" in str(result)


def test_no_base_still_anchors_to_root(split_roots):
    """Default behavior unchanged for repo-rooted tools (aetheria, kernel read)."""
    _, repo = split_roots
    resolved = resolve_within_root("docs/x.md", root=repo)
    assert resolved == repo / "docs" / "x.md"
