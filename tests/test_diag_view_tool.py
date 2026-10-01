"""house_diag tests — read-only diagnostic terminal view for citizens.

The mechanism claims: argv-only (no shell), curl pinned to 127.0.0.1, house
roots only, secrets refused, capped output, receipts written. Each test pins
one of those claims — a green suite here IS the trust boundary.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from soveryn.platform.diag_view_tool import (
    ALLOWED_ROOTS,
    build_house_diag_tool,
    diag_file,
    diag_gitlog,
    diag_http,
    diag_journal,
    diag_unit,
)
from soveryn.platform.tools.registry import ToolArgError

REPO = Path(__file__).resolve().parents[1]


def test_unit_rejects_injection():
    with pytest.raises(ToolArgError):
        diag_unit("x.service; reboot")
    with pytest.raises(ToolArgError):
        diag_unit("$(reboot)")
    with pytest.raises(ToolArgError):
        diag_unit("no-extension")


def test_http_is_localhost_only():
    out = diag_http(8095, "/search?q=test")  # real SearXNG probe
    assert "HTTP 200" in out
    with pytest.raises(ToolArgError):
        diag_http("example.com")
    with pytest.raises(ToolArgError):
        diag_http(8095, "/x rm -rf")  # no spaces/quotes in path


def test_path_is_house_roots_only_and_secrets_denied():
    with pytest.raises(ToolArgError):
        diag_file("/etc/shadow")
    with pytest.raises(ToolArgError):
        diag_file(str(Path.home() / ".ssh" / "config"))
    with pytest.raises(ToolArgError):
        diag_file(str(REPO / "data" / "secrets" / "whatever.env"))
    # an allowed root itself lists fine
    out = diag_file(str(Path.home() / "soveryn_eyes"))
    assert "latest.png" in out


def test_lines_are_clamped_not_absolute():
    out = diag_file(str(REPO / "README.md"), 10_000_000)
    assert 0 < len(out.splitlines()) <= 100
    with pytest.raises(ToolArgError):
        diag_file(str(REPO / "README.md"), "many")


def test_gitlog_needs_a_repo():
    out = diag_gitlog(str(REPO), 3)
    assert len(out.splitlines()) <= 3
    with pytest.raises(ToolArgError):
        diag_gitlog(str(Path.home() / "soveryn_eyes"))


def test_journal_rejects_bad_lines():
    with pytest.raises(ToolArgError):
        diag_journal("soveryn-searxng.service", "-1; rm")


def test_tool_handler_receipts_every_call(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "soveryn.platform.diag_view_tool._receipt_dir",
        lambda: tmp_path / "diag",
    )
    tool = build_house_diag_tool(owner_agent="aetheria")
    result = tool.handler({"action": "http", "port": 8095, "path": "/"})
    assert result["ok"] is True
    receipts = list((tmp_path / "diag").glob("diag-*.jsonl"))
    assert len(receipts) == 1
    line = json.loads(receipts[0].read_text())
    assert line["kind"] == "house_diag" and line["ok"] is True

    bad = pytest.raises(ToolArgError)
    with bad:
        tool.handler({"action": "http", "port": 99999999})
    assert len(list((tmp_path / "diag").glob("diag-*.jsonl"))) == 1


def test_allowlist_covers_expected_roots():
    names = [p.name for p in ALLOWED_ROOTS]
    assert "soveryn_vnext" in names and "teammates" in names
