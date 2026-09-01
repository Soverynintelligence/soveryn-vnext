"""Tool results with bytes must not kill a Kernel commission."""

import json

from soveryn.agents.loop import dump_tool_result


def test_dump_tool_result_decodes_bytes_instead_of_raising():
    raw = dump_tool_result({"ok": False, "output": b"hello \xff world", "n": 1})
    data = json.loads(raw)
    assert data["n"] == 1
    assert "hello" in data["output"]


def test_dump_tool_result_plain_dict_unchanged():
    raw = dump_tool_result({"ok": True, "output": "applied"})
    assert json.loads(raw) == {"ok": True, "output": "applied"}
