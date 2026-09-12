"""kernel_run — Messages ↔ CLI Kernel read-and-report door."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from soveryn.platform.kernel_run_tool import (
    REPORT_TOOLS,
    build_kernel_run_tool,
    resolve_repo,
    run_receipts,
    run_report,
    run_status,
)
from soveryn.platform.tools.registry import ToolArgError


def test_resolve_repo_rejects_outside(tmp_path, monkeypatch):
    import soveryn.platform.kernel_run_tool as mod

    monkeypatch.setattr(mod, "ALLOWED_ROOTS", (tmp_path / "house",))
    (tmp_path / "house").mkdir()
    with pytest.raises(ToolArgError, match="must be under"):
        resolve_repo(str(tmp_path / "other"))


def test_run_status_records_receipt(tmp_path, monkeypatch):
    import soveryn.platform.kernel_run_tool as mod

    monkeypatch.setattr(mod, "_data_root", lambda: tmp_path)
    monkeypatch.setattr(mod, "find_launcher", lambda: "/bin/kernel")

    class _Proc:
        returncode = 0
        stdout = "ACTIVE flash\nREADY.\n  * flash      OK     qwen @ 127.0.0.1:8888 (HTTP 200)\n"
        stderr = ""

    def fake_run(cmd, **kwargs):
        assert cmd == ["/bin/kernel", "status"]
        return _Proc()

    out = run_status(runner=fake_run)
    assert out["ok"] is True
    assert out["finish_reason"] == "stop"
    assert any(v.startswith("[PASS]") for v in out["verdict"])
    receipt = Path(out["receipt_path"])
    assert receipt.is_file()
    row = json.loads(receipt.read_text().strip().splitlines()[-1])
    assert row["kind"] == "kernel_run"
    assert row["origin"] == "messages"
    assert row["run_id"] == out["run_id"]


def test_run_report_refuses_mutate(tmp_path, monkeypatch):
    import soveryn.platform.kernel_run_tool as mod

    monkeypatch.setattr(mod, "_data_root", lambda: tmp_path)
    out = run_report("please mend the seats and commit")
    assert out["ok"] is False
    assert out["finish_reason"] == "mutate_refused"
    assert any("mutate_gate" in v for v in out["verdict"])


def test_run_report_locks_read_tools(tmp_path, monkeypatch):
    import soveryn.platform.kernel_run_tool as mod

    monkeypatch.setattr(mod, "_data_root", lambda: tmp_path)
    monkeypatch.setattr(mod, "find_launcher", lambda: "/bin/kernel")
    calls = []

    class _Proc:
        returncode = 0
        stdout = "file X exists\n"
        stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _Proc()

    out = run_report(
        "does seats.js exist?",
        repo=tmp_path,
        launcher="/bin/kernel",
        timeout_s=12,
        runner=fake_run,
    )
    assert out["ok"] is True
    cmd = calls[0]
    assert cmd[0] == "/bin/kernel"
    assert cmd[1] == "-p"
    assert "ORIGIN=messages" in cmd[2]
    assert "--tools" in cmd
    assert cmd[cmd.index("--tools") + 1] == REPORT_TOOLS
    assert "bash" not in REPORT_TOOLS


def test_run_report_tool_round_limit_not_success(tmp_path, monkeypatch):
    import soveryn.platform.kernel_run_tool as mod

    monkeypatch.setattr(mod, "_data_root", lambda: tmp_path)

    class _Proc:
        returncode = 0
        stdout = "hit tool_round_limit while searching\n"
        stderr = ""

    out = run_report(
        "where is X?",
        repo=tmp_path,
        launcher="/bin/kernel",
        runner=lambda *a, **k: _Proc(),
    )
    assert out["ok"] is False
    assert out["finish_reason"] == "tool_round_limit"


def test_run_receipts_marks_tool_round_limit_fail(tmp_path, monkeypatch):
    import soveryn.platform.kernel_run_tool as mod

    monkeypatch.setattr(mod, "_data_root", lambda: tmp_path)
    d = tmp_path / "black_box" / "kernel"
    d.mkdir(parents=True)
    (d / "abc.jsonl").write_text(
        json.dumps(
            {
                "finish_reason": "tool_round_limit",
                "telemetry": {"tool_round_limit_hit": True},
                "final_content": "oops",
                "started_at": "2026-09-10T12:00:00-04:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    out = run_receipts(limit=3)
    assert out["ok"] is True
    assert out["entries"][0]["ok"] is False
    assert out["entries"][0]["finish_reason"] == "tool_round_limit"


def test_tool_handler_actions():
    tool = build_kernel_run_tool()
    with pytest.raises(ToolArgError, match="action"):
        tool.handler({"action": "explode"})
