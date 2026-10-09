"""house_diag tests — read-only diagnostic terminal view for citizens.

The mechanism claims: argv-only (no shell), curl pinned to 127.0.0.1, house
roots only, secrets refused, capped output, receipts written. Each test pins
one of those claims — a green suite here IS the trust boundary.
"""
from __future__ import annotations

import inspect
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from soveryn.paths import SoverynPaths
from soveryn.platform.diag_view_tool import (
    ALLOWED_ROOTS,
    build_house_diag_tool,
    diag_file,
    diag_gitlog,
    diag_http,
    diag_journal,
    diag_unit,
    house_diag,
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


def test_http_is_localhost_only(monkeypatch):
    monkeypatch.setattr(
        "soveryn.platform.diag_view_tool._run",
        lambda argv: "HTTP 200 text/html",
    )
    out = diag_http(8095, "/search?q=test")
    assert "HTTP 200" in out
    with pytest.raises(ToolArgError):
        diag_http("example.com")
    with pytest.raises(ToolArgError):
        diag_http(8095, "/x rm -rf")  # no spaces/quotes in path


def test_path_is_house_roots_only_and_secrets_denied(tmp_path, monkeypatch):
    eyes = tmp_path / "soveryn_eyes"
    eyes.mkdir()
    (eyes / "latest.png").write_bytes(b"x")
    monkeypatch.setattr(
        "soveryn.platform.diag_view_tool.ALLOWED_ROOTS",
        ALLOWED_ROOTS + (eyes,),
    )
    with pytest.raises(ToolArgError):
        diag_file("/etc/shadow")
    with pytest.raises(ToolArgError):
        diag_file(str(Path.home() / ".ssh" / "config"))
    with pytest.raises(ToolArgError):
        diag_file(str(REPO / "data" / "secrets" / "whatever.env"))
    out = diag_file(str(eyes))
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
    monkeypatch.setattr(
        "soveryn.platform.diag_view_tool._run",
        lambda argv: "HTTP 200 text/html",
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
    assert SoverynPaths.root() in ALLOWED_ROOTS
    assert "teammates" in names


def _git_repo(path: Path) -> None:
    """One-commit repo so gitlog tests do not depend on the checkout."""
    env = os.environ | {
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    subprocess.run(["git", "init", "-q"], cwd=path, check=True, env=env)
    (path / "note.txt").write_text("hello\n")
    subprocess.run(["git", "add", "note.txt"], cwd=path, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=path, check=True, env=env)


def test_gitlog_dispatch_accepts_path_and_repo(tmp_path, monkeypatch):
    """Agents send schema key `path`. `repo` stays as a backward-compat alias.

    Calling diag_gitlog() directly hides a dispatch that drops `path`
    (the pre-35828a3 bug: args.get("repo") only).
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_repo(repo)
    monkeypatch.setattr(
        "soveryn.platform.diag_view_tool.ALLOWED_ROOTS",
        (repo.resolve(),),
    )
    monkeypatch.setattr(
        "soveryn.platform.diag_view_tool._receipt_dir",
        lambda: tmp_path / "receipts",
    )
    tool = build_house_diag_tool(owner_agent="test")

    by_path = tool.handler({"action": "gitlog", "path": str(repo), "lines": 5})
    assert by_path["ok"] is True
    assert "seed" in by_path["output"]

    by_repo = tool.handler({"action": "gitlog", "repo": str(repo), "lines": 5})
    assert by_repo["ok"] is True
    assert "seed" in by_repo["output"]

    filed = tool.handler({"action": "file", "path": str(repo / "note.txt"), "lines": 5})
    assert filed["ok"] is True
    assert "hello" in filed["output"]

    receipts = list((tmp_path / "receipts").glob("diag-*.jsonl"))
    assert len(receipts) == 3
    assert all(json.loads(r.read_text())["ok"] is True for r in receipts)


def test_schema_covers_keys_house_diag_reads():
    """A key the dispatch reads but the schema does not declare is how
    gitlog dropped `path` while `file` worked. `repo` is the one allowed
    undeclared alias."""
    src = inspect.getsource(house_diag)
    read = set(re.findall(r'args\.get\(\s*"([^"]+)"\s*\)', src))
    declared = set(build_house_diag_tool(owner_agent="test").schema["properties"])
    assert read - declared == {"repo"}
    assert "path" in read and "path" in declared
