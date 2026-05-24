"""Tests for soveryn.backup.rotation. Pure-function tests."""

from pathlib import Path
import pytest

from soveryn.backup.rotation import (
    select_snapshots_for_deletion,
    list_finalised_snapshots,
)
from soveryn.backup.code_snapshot import PARTIAL_SUFFIX


def _snap(name: str) -> Path:
    return Path(f"/dest/{name}")


# ─── select_snapshots_for_deletion ───────────────────────────────────────────

def test_retain_equals_count_deletes_none():
    snaps = [_snap(f"2026-05-{d:02d}") for d in range(10, 24)]  # 14 snapshots
    assert select_snapshots_for_deletion(snaps, retain=14) == []


def test_retain_less_than_count_deletes_oldest():
    snaps = [_snap(f"2026-05-{d:02d}") for d in range(10, 25)]  # 15 snapshots
    to_delete = select_snapshots_for_deletion(snaps, retain=14)
    assert len(to_delete) == 1
    assert to_delete[0].name == "2026-05-10"


def test_retain_much_less_deletes_many_oldest_first():
    snaps = [_snap(f"2026-05-{d:02d}") for d in range(1, 31)]  # 30
    to_delete = select_snapshots_for_deletion(snaps, retain=14)
    # 16 oldest get deleted
    assert len(to_delete) == 16
    assert to_delete[0].name == "2026-05-01"
    assert to_delete[-1].name == "2026-05-16"


def test_empty_input_returns_empty():
    assert select_snapshots_for_deletion([], retain=14) == []


def test_just_created_never_deleted(tmp_path):
    """Jon constraint 9: the just-created snapshot must survive rotation."""
    snaps = [_snap(f"2026-05-{d:02d}") for d in range(10, 25)]  # 15
    just_created = _snap("2026-05-10")  # oldest, normally first to delete
    to_delete = select_snapshots_for_deletion(snaps, retain=14,
                                              just_created=just_created)
    assert just_created not in to_delete


def test_just_created_protected_even_with_retain_zero():
    snaps = [_snap("2026-05-24")]
    just_created = _snap("2026-05-24")
    to_delete = select_snapshots_for_deletion(snaps, retain=0,
                                              just_created=just_created)
    assert to_delete == []


def test_retain_zero_deletes_everything_except_just_created():
    snaps = [_snap(f"2026-05-{d:02d}") for d in range(10, 24)]  # 14
    just_created = _snap("2026-05-23")
    to_delete = select_snapshots_for_deletion(snaps, retain=0,
                                              just_created=just_created)
    assert just_created not in to_delete
    assert len(to_delete) == 13


def test_partial_dirs_never_selected_for_deletion():
    """Defense: rotation skips .partial dirs even if they're in the input."""
    snaps = [
        _snap("2026-05-22"),
        _snap(f"2026-05-23{PARTIAL_SUFFIX}"),
        _snap("2026-05-24"),
    ]
    to_delete = select_snapshots_for_deletion(snaps, retain=1)
    assert all(not p.name.endswith(PARTIAL_SUFFIX) for p in to_delete)


def test_negative_retain_raises():
    with pytest.raises(ValueError, match="retain"):
        select_snapshots_for_deletion([_snap("2026-05-24")], retain=-1)


# ─── list_finalised_snapshots ────────────────────────────────────────────────

def test_list_finalised_returns_only_dated_dirs(tmp_path):
    (tmp_path / "2026-05-22").mkdir()
    (tmp_path / "2026-05-23").mkdir()
    (tmp_path / f"2026-05-24{PARTIAL_SUFFIX}").mkdir()
    (tmp_path / "notes.txt").write_text("ignore")
    (tmp_path / "junk").mkdir()
    result = list_finalised_snapshots(tmp_path)
    names = sorted(p.name for p in result)
    assert names == ["2026-05-22", "2026-05-23"]


def test_list_finalised_empty_when_dest_missing(tmp_path):
    missing = tmp_path / "nope"
    assert list_finalised_snapshots(missing) == []


def test_list_finalised_handles_time_suffixed_names(tmp_path):
    (tmp_path / "2026-05-24_143045").mkdir()
    result = list_finalised_snapshots(tmp_path)
    assert len(result) == 1
    assert result[0].name == "2026-05-24_143045"
