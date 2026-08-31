"""Kernel run_aider — default write path from Messages."""

import pytest

from soveryn.platform.aider_tool import build_run_aider_tool, run_aider
from soveryn.platform.tools.registry import ToolArgError


def test_run_aider_invokes_kernel_yes_message(tmp_path):
    calls = []

    class _Proc:
        returncode = 0
        stdout = "Applied edit to seats.py\n"
        stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return _Proc()

    out = run_aider(
        "fix the seats",
        repo=tmp_path,
        launcher="/bin/soveryn-aider",
        timeout_s=12,
        files=("seats.py",),
        runner=fake_run,
    )
    assert out["ok"] is True
    cmd, kw = calls[0]
    assert cmd[:5] == [
        "/bin/soveryn-aider",
        "--kernel",
        "--yes",
        "--no-pretty",
        "--message",
    ]
    assert cmd[5] == "fix the seats"
    assert cmd[6] == "seats.py"
    assert kw["cwd"] == str(tmp_path)


def test_run_aider_tool_empty_prompt():
    tool = build_run_aider_tool()
    with pytest.raises(ToolArgError, match="prompt"):
        tool.handler({"prompt": "  "})
