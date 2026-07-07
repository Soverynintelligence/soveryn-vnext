"""Tests for Vett's read-only git-awareness tools.

Vett can read a file's *content*; these tools let her also see *where it lives*
in the repo — branch, dirty/clean, staged/modified/untracked, history, and the
working diff. Everything here is READ-ONLY: the safety-critical property is that
calling any of these tools never mutates the repository.

Each test builds a throwaway git repo in a tmp dir (like the delegation worktree
tests) so no real repo state is touched.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from soveryn.agents.vett.tools.git import (
    build_git_status_tool,
    build_git_log_tool,
    build_git_diff_tool,
    register_vett_git_tools,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, capture_output=True, text=True,
    ).stdout


def _init_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "vett@soveryn.test")
    _git(root, "config", "user.name", "Vett Test")
    _git(root, "checkout", "-q", "-b", "main")
    (root / "README.md").write_text("# hello\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "initial commit")
    return root


@pytest.fixture
def repo(tmp_path):
    return _init_repo(tmp_path / "proj")


# ─── git_status ───────────────────────────────────────────────────────────────

class TestGitStatus:
    def _call(self, path):
        tool = build_git_status_tool()
        return tool.handler({"path": str(path)})

    def test_clean_repo(self, repo):
        out = self._call(repo)
        assert out["branch"] == "main"
        assert out["clean"] is True
        assert out["files"] == []
        assert Path(out["repo_root"]).resolve() == repo.resolve()
        assert len(out["head"]) >= 7  # short sha

    def test_modified_tracked_file(self, repo):
        (repo / "README.md").write_text("# hello world\n")
        out = self._call(repo)
        assert out["clean"] is False
        paths = {f["path"]: f["status"] for f in out["files"]}
        assert "README.md" in paths
        assert "modified" in paths["README.md"]

    def test_staged_file(self, repo):
        (repo / "new.py").write_text("x = 1\n")
        _git(repo, "add", "new.py")
        out = self._call(repo)
        paths = {f["path"]: f["status"] for f in out["files"]}
        assert "staged" in paths["new.py"]

    def test_untracked_file(self, repo):
        (repo / "scratch.txt").write_text("notes\n")
        out = self._call(repo)
        paths = {f["path"]: f["status"] for f in out["files"]}
        assert paths["scratch.txt"] == "untracked"

    def test_reflects_feature_branch(self, repo):
        _git(repo, "checkout", "-q", "-b", "feat/thing")
        out = self._call(repo)
        assert out["branch"] == "feat/thing"

    def test_resolves_repo_from_a_file_path(self, repo):
        # Passing a file *inside* the repo resolves to the repo root.
        out = self._call(repo / "README.md")
        assert Path(out["repo_root"]).resolve() == repo.resolve()

    def test_not_a_repo(self, tmp_path):
        plain = tmp_path / "not_git"
        plain.mkdir()
        out = self._call(plain)
        assert out["error"] == "not_a_repo"

    def test_missing_path(self, tmp_path):
        out = self._call(tmp_path / "does_not_exist")
        assert out["error"] in ("not_found", "not_a_repo")


# ─── git_log ──────────────────────────────────────────────────────────────────

class TestGitLog:
    def _call(self, path, **kw):
        tool = build_git_log_tool()
        return tool.handler({"path": str(path), **kw})

    def test_returns_commits_newest_first(self, repo):
        (repo / "a.py").write_text("a\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "second commit")
        out = self._call(repo)
        assert out["commits"][0]["subject"] == "second commit"
        assert out["commits"][1]["subject"] == "initial commit"
        for c in out["commits"]:
            assert len(c["sha"]) >= 7
            assert c["date"]  # non-empty date

    def test_max_count_respected(self, repo):
        for i in range(5):
            (repo / f"f{i}.py").write_text(f"{i}\n")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", f"commit {i}")
        out = self._call(repo, max_count=3)
        assert len(out["commits"]) == 3

    def test_scoped_to_a_file(self, repo):
        (repo / "tracked.py").write_text("v1\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "add tracked")
        (repo / "other.py").write_text("o\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "add other")
        out = self._call(repo / "tracked.py")
        subjects = [c["subject"] for c in out["commits"]]
        assert "add tracked" in subjects
        assert "add other" not in subjects

    def test_not_a_repo(self, tmp_path):
        plain = tmp_path / "plain"
        plain.mkdir()
        out = self._call(plain)
        assert out["error"] == "not_a_repo"


# ─── git_diff ─────────────────────────────────────────────────────────────────

class TestGitDiff:
    def _call(self, path, **kw):
        tool = build_git_diff_tool()
        return tool.handler({"path": str(path), **kw})

    def test_working_diff(self, repo):
        (repo / "README.md").write_text("# hello world changed\n")
        out = self._call(repo)
        assert "changed" in out["diff"]
        assert out["staged"] is False

    def test_staged_diff(self, repo):
        (repo / "README.md").write_text("# staged change\n")
        _git(repo, "add", "-A")
        out = self._call(repo, staged=True)
        assert "staged change" in out["diff"]
        assert out["staged"] is True

    def test_clean_repo_empty_diff(self, repo):
        out = self._call(repo)
        assert out["diff"] == ""
        assert out["truncated"] is False

    def test_large_diff_truncated(self, repo):
        big = "\n".join(f"line {i}" for i in range(5000)) + "\n"
        (repo / "README.md").write_text(big)
        out = self._call(repo, max_lines=200)
        assert out["truncated"] is True
        assert out["diff"].count("\n") <= 205  # cap + small header slack

    def test_not_a_repo(self, tmp_path):
        plain = tmp_path / "plain"
        plain.mkdir()
        out = self._call(plain)
        assert out["error"] == "not_a_repo"


# ─── Safety: read-only ────────────────────────────────────────────────────────

def test_tools_never_mutate_repo(repo):
    """The load-bearing guarantee: calling every tool leaves the repo byte-identical."""
    (repo / "README.md").write_text("# dirty\n")
    (repo / "untracked.txt").write_text("u\n")
    _git(repo, "add", "README.md")  # one staged, one untracked

    head_before = _git(repo, "rev-parse", "HEAD").strip()
    status_before = _git(repo, "status", "--porcelain")
    reflog_before = _git(repo, "reflog").strip()

    build_git_status_tool().handler({"path": str(repo)})
    build_git_log_tool().handler({"path": str(repo)})
    build_git_diff_tool().handler({"path": str(repo)})
    build_git_diff_tool().handler({"path": str(repo), "staged": True})

    assert _git(repo, "rev-parse", "HEAD").strip() == head_before
    assert _git(repo, "status", "--porcelain") == status_before
    assert _git(repo, "reflog").strip() == reflog_before


# ─── Ownership + registration ─────────────────────────────────────────────────

def test_tools_are_vett_owned():
    for build in (build_git_status_tool, build_git_log_tool, build_git_diff_tool):
        assert build().owner == "vett"


def test_register_adds_three_tools():
    registered = []

    class FakeRegistry:
        def register(self, spec):
            registered.append(spec.name)

    register_vett_git_tools(FakeRegistry())
    assert set(registered) == {"git_status", "git_log", "git_diff"}
