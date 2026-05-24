"""Tests for soveryn.backup.daemon CLI."""

import json
from pathlib import Path
from unittest.mock import patch
import pytest

from soveryn.backup.code_snapshot import METADATA_FILENAME
from soveryn.backup.daemon import (
    BackupDaemonError, DEFAULT_REPO, DEFAULT_DEST, DEFAULT_RETAIN,
    _build_parser, main, run_once,
)


@pytest.fixture
def fake_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "x.py").write_text("print(1)\n")
    return repo


# ─── Parser defaults ─────────────────────────────────────────────────────────

def test_parser_defaults():
    args = _build_parser().parse_args(["--once"])
    assert args.repo == DEFAULT_REPO
    assert args.dest == DEFAULT_DEST
    assert args.retain == DEFAULT_RETAIN
    assert args.once is True


def test_parser_repo_default_is_hardcoded_vnext():
    """Constraint 4: must not read from EnvConfig."""
    assert str(DEFAULT_REPO) == "/home/jon-deoliveira/soveryn_vnext"


def test_parser_dest_default_is_external_drive():
    assert "easystore" in str(DEFAULT_DEST)


def test_parser_overrides(tmp_path):
    args = _build_parser().parse_args([
        "--once", "--repo", str(tmp_path), "--dest", "/tmp/x", "--retain", "7"
    ])
    assert args.repo == tmp_path
    assert args.dest == Path("/tmp/x")
    assert args.retain == 7


# ─── main() return codes ─────────────────────────────────────────────────────

def test_main_without_once_returns_2():
    rc = main([])
    assert rc == 2


def test_main_negative_retain_returns_2(fake_repo, tmp_path):
    rc = main(["--once", "--repo", str(fake_repo), "--dest", str(tmp_path / "d"),
               "--retain", "-1"])
    assert rc == 2


def test_main_missing_dest_parent_returns_1(fake_repo):
    rc = main(["--once", "--repo", str(fake_repo),
               "--dest", "/nonexistent/parent/dir"])
    assert rc == 1


def test_main_happy_path_returns_0_and_creates_snapshot(fake_repo, tmp_path, capsys):
    dest = tmp_path / "backups"
    rc = main(["--once", "--repo", str(fake_repo), "--dest", str(dest),
               "--retain", "14"])
    assert rc == 0
    snapshots = list(dest.iterdir())
    finalised = [p for p in snapshots if not p.name.endswith(".partial")]
    assert len(finalised) == 1
    # Snapshot has metadata
    meta = json.loads((finalised[0] / METADATA_FILENAME).read_text())
    assert meta["source_path"] == str(fake_repo.resolve())
    captured = capsys.readouterr()
    assert "[backup]" in captured.out


def test_main_missing_source_returns_1(tmp_path):
    rc = main(["--once", "--repo", str(tmp_path / "nope"),
               "--dest", str(tmp_path / "d")])
    assert rc == 1


# ─── run_once + rotation interaction ─────────────────────────────────────────

def test_run_once_first_snapshot_no_prune(fake_repo, tmp_path):
    dest = tmp_path / "d"
    result, deleted = run_once(fake_repo, dest, retain=14)
    assert result.snapshot_dir.exists()
    assert deleted == []


def test_run_once_prunes_when_over_retain(fake_repo, tmp_path):
    """Pre-seed N+1 old snapshots; run_once should produce one new + delete oldest."""
    dest = tmp_path / "d"
    dest.mkdir()
    # Seed 14 old dated dirs
    for d in range(1, 15):
        (dest / f"2026-04-{d:02d}").mkdir()
    result, deleted = run_once(fake_repo, dest, retain=14)
    # Now there are 15 finalised + we made it 14 by deleting oldest
    finalised = [p for p in dest.iterdir() if p.is_dir() and not p.name.endswith(".partial")]
    assert len(finalised) == 14
    assert result.snapshot_dir.exists()
    # Just-created MUST NOT have been deleted
    assert result.snapshot_dir not in deleted


def test_run_once_never_deletes_just_created_even_if_retain_zero(fake_repo, tmp_path):
    """Jon constraint 9: even retain=0 protects the new one."""
    dest = tmp_path / "d"
    dest.mkdir()
    (dest / "2026-04-01").mkdir()
    result, deleted = run_once(fake_repo, dest, retain=0)
    assert result.snapshot_dir.exists()
    assert result.snapshot_dir not in deleted
    # Old snapshot WAS deleted
    assert any(p.name == "2026-04-01" for p in deleted)
