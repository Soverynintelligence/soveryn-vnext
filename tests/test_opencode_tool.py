"""Kernel run_opencode — OpenCode mend from Messages, not AgentLoop bash."""

from __future__ import annotations

from pathlib import Path

import pytest

from soveryn.platform.opencode_tool import (
    build_run_opencode_tool,
    resolve_repo,
    run_opencode,
)
from soveryn.platform.tools.registry import ToolArgError


def test_resolve_repo_rejects_outside_house(tmp_path, monkeypatch):
    import soveryn.platform.opencode_tool as mod

    monkeypatch.setattr(mod, "ALLOWED_ROOTS", (tmp_path / "house",))
    (tmp_path / "house").mkdir()
    with pytest.raises(ToolArgError, match="must be under"):
        resolve_repo(str(tmp_path / "other"))


def test_resolve_repo_allows_house_tree(tmp_path, monkeypatch):
    import soveryn.platform.opencode_tool as mod

    house = tmp_path / "house"
    house.mkdir()
    monkeypatch.setattr(mod, "ALLOWED_ROOTS", (house,))
    monkeypatch.setattr(mod, "DEFAULT_REPO", house)
    assert resolve_repo(None) == house.resolve()
    nested = house / "pkg"
    nested.mkdir()
    assert resolve_repo(str(nested)) == nested.resolve()


def test_run_opencode_invokes_launcher_auto(tmp_path):
    calls = []

    class _Proc:
        returncode = 0
        stdout = "patched seats\n"
        stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return _Proc()

    out = run_opencode(
        "fix the seats",
        repo=tmp_path,
        launcher="/bin/soveryn-opencode",
        timeout_s=12,
        runner=fake_run,
    )
    assert out["ok"] is True
    assert "patched" in out["output"]
    cmd, kw = calls[0]
    assert cmd[:4] == ["/bin/soveryn-opencode", "run", "--auto", "--dir"]
    assert cmd[4] == str(tmp_path)
    assert cmd[5] == "fix the seats"
    assert kw["timeout"] == 12
    assert kw["cwd"] == str(tmp_path)


def test_run_opencode_tool_empty_prompt():
    tool = build_run_opencode_tool()
    with pytest.raises(ToolArgError, match="prompt"):
        tool.handler({"prompt": "  "})
