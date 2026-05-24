"""Tests for soveryn.backup.code_snapshot. Uses tmp_path; never touches real backup dirs."""

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from soveryn.backup.code_snapshot import (
    DEFAULT_EXCLUDES, METADATA_FILENAME, PARTIAL_SUFFIX,
    SnapshotResult, TOOL_VERSION,
    _count_files_and_bytes, _find_previous_snapshot, _read_git_head,
    _resolve_snapshot_paths, snapshot_repo,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def fake_repo(tmp_path):
    """Build a small fake repo with tracked + untracked + __pycache__ files."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("print('hello')\n")
    (repo / "untracked.py").write_text("# untracked\n")
    pkg = repo / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    pyc = pkg / "__pycache__"
    pyc.mkdir()
    (pyc / "mod.cpython-311.pyc").write_bytes(b"\x00\x01\x02fake bytecode")
    # Caches that MUST be excluded
    cache = repo / ".pytest_cache"
    cache.mkdir()
    (cache / "junk").write_text("ignore me")
    # Fake .git/HEAD for the metadata
    git_dir = repo / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n")
    return repo


@pytest.fixture
def dest(tmp_path):
    return tmp_path / "backups"


# ─── _read_git_head ──────────────────────────────────────────────────────────

def test_read_git_head_returns_trimmed(tmp_path):
    repo = tmp_path / "r"
    (repo / ".git").mkdir(parents=True)
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n  \n")
    assert _read_git_head(repo) == "ref: refs/heads/main"


def test_read_git_head_missing_returns_none(tmp_path):
    assert _read_git_head(tmp_path) is None


def test_read_git_head_no_subprocess(monkeypatch, tmp_path):
    """Defense: ensure no subprocess spawn happens during git head read."""
    repo = tmp_path / "r"
    (repo / ".git").mkdir(parents=True)
    (repo / ".git" / "HEAD").write_text("abc123\n")
    called = {"n": 0}
    real_popen = __import__("subprocess").Popen
    def fail_popen(*a, **k):
        called["n"] += 1
        raise AssertionError("subprocess called during _read_git_head")
    monkeypatch.setattr("subprocess.Popen", fail_popen)
    assert _read_git_head(repo) == "abc123"
    assert called["n"] == 0


# ─── _resolve_snapshot_paths ─────────────────────────────────────────────────

def test_resolve_paths_uses_date_when_no_collision(dest):
    now = datetime(2026, 5, 24, 4, 30, tzinfo=timezone.utc)
    partial, final = _resolve_snapshot_paths(dest, now)
    assert final.name == "2026-05-24"
    assert partial.name == f"2026-05-24{PARTIAL_SUFFIX}"


def test_resolve_paths_disambiguates_on_collision(dest):
    """If today's snapshot already exists, append HHMMSS."""
    dest.mkdir()
    (dest / "2026-05-24").mkdir()
    now = datetime(2026, 5, 24, 14, 30, 45, tzinfo=timezone.utc)
    partial, final = _resolve_snapshot_paths(dest, now)
    assert final.name == "2026-05-24_143045"
    assert partial.name == f"2026-05-24_143045{PARTIAL_SUFFIX}"


# ─── _find_previous_snapshot ─────────────────────────────────────────────────

def test_find_previous_returns_latest(dest):
    dest.mkdir()
    (dest / "2026-05-22").mkdir()
    (dest / "2026-05-23").mkdir()
    (dest / "2026-05-24").mkdir()
    assert _find_previous_snapshot(dest).name == "2026-05-24"


def test_find_previous_skips_partial(dest):
    dest.mkdir()
    (dest / "2026-05-22").mkdir()
    (dest / f"2026-05-24{PARTIAL_SUFFIX}").mkdir()
    assert _find_previous_snapshot(dest).name == "2026-05-22"


def test_find_previous_none_when_empty(dest):
    dest.mkdir()
    assert _find_previous_snapshot(dest) is None


def test_find_previous_skips_garbage_dir_names(dest):
    dest.mkdir()
    (dest / "notes").mkdir()
    (dest / "tmp123").mkdir()
    (dest / "2026-05-24").mkdir()
    assert _find_previous_snapshot(dest).name == "2026-05-24"


# ─── snapshot_repo — rsync path ──────────────────────────────────────────────

def test_snapshot_uses_rsync_when_available(fake_repo, dest):
    """If rsync is on PATH, snapshot uses it. (Real rsync IS available in dev env.)"""
    if shutil.which("rsync") is None:
        pytest.skip("rsync not installed")
    result = snapshot_repo(fake_repo, dest)
    assert result.used_rsync is True
    assert result.snapshot_dir.exists()
    assert (result.snapshot_dir / "app.py").read_text() == "print('hello')\n"
    assert (result.snapshot_dir / "pkg" / "__pycache__" / "mod.cpython-311.pyc").exists()
    # Cache excluded
    assert not (result.snapshot_dir / ".pytest_cache").exists()


def test_snapshot_includes_untracked_files(fake_repo, dest):
    if shutil.which("rsync") is None:
        pytest.skip("rsync not installed")
    result = snapshot_repo(fake_repo, dest)
    assert (result.snapshot_dir / "untracked.py").exists()


def test_snapshot_includes_pycache(fake_repo, dest):
    if shutil.which("rsync") is None:
        pytest.skip("rsync not installed")
    result = snapshot_repo(fake_repo, dest)
    assert (result.snapshot_dir / "pkg" / "__pycache__" / "mod.cpython-311.pyc").exists()


def test_snapshot_excludes_pytest_cache(fake_repo, dest):
    if shutil.which("rsync") is None:
        pytest.skip("rsync not installed")
    result = snapshot_repo(fake_repo, dest)
    assert not (result.snapshot_dir / ".pytest_cache").exists()


# ─── shutil fallback path ────────────────────────────────────────────────────

def test_snapshot_falls_back_to_shutil_when_rsync_unavailable(fake_repo, dest):
    result = snapshot_repo(fake_repo, dest, rsync_available=False)
    assert result.used_rsync is False
    assert result.snapshot_dir.exists()
    assert (result.snapshot_dir / "app.py").exists()
    assert (result.snapshot_dir / "untracked.py").exists()
    # __pycache__ still included
    assert (result.snapshot_dir / "pkg" / "__pycache__" / "mod.cpython-311.pyc").exists()
    # Cache still excluded
    assert not (result.snapshot_dir / ".pytest_cache").exists()


# ─── SNAPSHOT.json metadata ──────────────────────────────────────────────────

def test_metadata_file_written(fake_repo, dest):
    result = snapshot_repo(fake_repo, dest, rsync_available=False)
    meta_path = result.snapshot_dir / METADATA_FILENAME
    assert meta_path.exists()
    meta = json.loads(meta_path.read_text())
    assert meta["source_path"] == str(fake_repo.resolve())
    assert meta["tool_version"] == TOOL_VERSION
    assert meta["hostname"]  # non-empty
    assert "timestamp" in meta
    assert meta["file_count"] > 0
    assert meta["byte_count"] > 0
    assert meta["git_head"] == "ref: refs/heads/main"
    assert meta["link_dest"] is None  # first snapshot in this dest
    assert ".pytest_cache/" in meta["excludes"]


def test_metadata_link_dest_set_on_second_run(fake_repo, dest):
    r1 = snapshot_repo(fake_repo, dest, rsync_available=False,
                       now=datetime(2026, 5, 23, 4, 30, tzinfo=timezone.utc))
    r2 = snapshot_repo(fake_repo, dest, rsync_available=False,
                       now=datetime(2026, 5, 24, 4, 30, tzinfo=timezone.utc))
    meta2 = json.loads((r2.snapshot_dir / METADATA_FILENAME).read_text())
    assert meta2["link_dest"] == str(r1.snapshot_dir)


def test_metadata_git_head_none_when_no_git(tmp_path, dest):
    repo = tmp_path / "nogit"
    repo.mkdir()
    (repo / "x.py").write_text("pass")
    result = snapshot_repo(repo, dest, rsync_available=False)
    meta = json.loads((result.snapshot_dir / METADATA_FILENAME).read_text())
    assert meta["git_head"] is None


# ─── Atomicity ───────────────────────────────────────────────────────────────

def test_partial_dir_renamed_to_final(fake_repo, dest):
    result = snapshot_repo(fake_repo, dest, rsync_available=False)
    assert result.snapshot_dir.exists()
    assert not (dest / f"{result.snapshot_dir.name}{PARTIAL_SUFFIX}").exists()


def test_existing_partial_dir_raises(fake_repo, dest):
    """A stuck .partial from a prior failed run blocks the next attempt
    so the operator notices and inspects it."""
    now = datetime(2026, 5, 24, 4, 30, tzinfo=timezone.utc)
    dest.mkdir()
    (dest / f"2026-05-24{PARTIAL_SUFFIX}").mkdir()
    with pytest.raises(RuntimeError, match="prior .partial"):
        snapshot_repo(fake_repo, dest, rsync_available=False, now=now)


# ─── Source-not-found ────────────────────────────────────────────────────────

def test_missing_source_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        snapshot_repo(tmp_path / "does_not_exist", tmp_path / "dest")


# ─── File counting ──────────────────────────────────────────────────────────

def test_count_excludes_metadata_file(tmp_path):
    d = tmp_path / "d"
    d.mkdir()
    (d / "a.txt").write_text("a")
    (d / "b.txt").write_text("bb")
    (d / METADATA_FILENAME).write_text("meta")
    fc, bc = _count_files_and_bytes(d, skip_filename=METADATA_FILENAME)
    assert fc == 2
    assert bc == 3
