"""Regression: house_diag gitlog path alias (commit 35828a3).

Pre-fix, the gitlog action only read args["repo"]; callers passing the
documented "path" arg (the schema's own field for gitlog) got a ToolArgError
("not a git repo: None"). 8 dispatches failed on exactly that. The fix reads
path first, falling back to repo for backward compatibility.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from soveryn.platform.diag_view_tool import house_diag
from soveryn.platform.tools.registry import ToolArgError

REPO = "/home/jon-deoliveira/soveryn_vnext"


def test_gitlog_accepts_path_alias() -> None:
    """The exact repro that failed 8x pre-fix: gitlog with path=, not repo=."""
    result = house_diag("gitlog", {"path": REPO})
    assert result
    assert any(
        line for line in result.splitlines()
        if line and not line.startswith("[command failed")
    )


def test_gitlog_accepts_repo_kwarg_backward_compat() -> None:
    """Backward compat: the original repo= spelling still works."""
    result = house_diag("gitlog", {"repo": REPO})
    assert result
    assert any(
        line for line in result.splitlines()
        if line and not line.startswith("[command failed")
    )


def test_gitlog_rejects_missing_repo() -> None:
    """Neither spelling: ToolArgError, not a silent 'not a git repo: None'."""
    with pytest.raises(ToolArgError):
        house_diag("gitlog", {})


def test_gitlog_rejects_non_repo_path() -> None:
    """A real directory without .git is refused with a clear error.

    The scratch dir must sit under a house root: the root guard in
    _validated_path fires before the .git check, so a pytest tmp_path
    (under /tmp) would exercise the wrong branch and never prove the
    "not a git repo" refusal.
    """
    scratch = Path(
        tempfile.mkdtemp(dir=Path.home() / "teammates", prefix="house_diag_test_")
    )
    try:
        assert not (scratch / ".git").exists()
        with pytest.raises(ToolArgError, match="not a git repo"):
            house_diag("gitlog", {"path": str(scratch)})
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
