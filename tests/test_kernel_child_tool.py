"""kernel_child tool — list/stop against the job store."""
from soveryn.platform.kernel_child_tool import build_kernel_child_tool
from soveryn.platform.kernel_jobs import reset_store_for_tests
from soveryn.platform.tools.registry import ToolArgError
import pytest


def test_list_empty():
    reset_store_for_tests()
    tool = build_kernel_child_tool()
    out = tool.handler({"action": "list"})
    assert out["ok"] is True
    assert out["jobs"] == []


def test_stop_unknown():
    reset_store_for_tests()
    tool = build_kernel_child_tool()
    out = tool.handler({"action": "stop", "job_id": "nope"})
    assert out["ok"] is False
    assert "unknown" in out["error"]


def test_bad_action():
    tool = build_kernel_child_tool()
    with pytest.raises(ToolArgError):
        tool.handler({"action": "spawn"})
