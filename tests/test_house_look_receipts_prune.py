"""house_look receipt retention — newest 50 survive, older ones pruned.

data/black_box/house_look/ grows one JSONL file per look forever. As of
2026-09-24 every _write_receipt call prunes to HOUSE_LOOK_RECEIPT_KEEP
newest files. These tests fake 55 receipts in a tmp dir, point the
receipt dir at it, trigger a write, and assert only 50 remain — the
newest 50.
"""
from __future__ import annotations

import os
import time

import pytest

from soveryn.platform import house_look_tool
from soveryn.platform.house_look_tool import (
    HOUSE_LOOK_RECEIPT_KEEP,
    _prune_receipts,
    _receipt_dir,
    _write_receipt,
)


def _fake_receipts(count: int) -> None:
    """Create `count` look-*.jsonl files with distinct, ascending mtimes."""
    now = time.time()
    for i in range(count):
        path = _receipt_dir() / f"look-fake-{i:04d}.jsonl"
        path.write_text(
            f'{{"kind": "house_look", "run_id": "fake-{i:04d}"}}\n',
            encoding="utf-8",
        )
        stamp = now - (count - i) * 60  # oldest first, 1 min apart
        os.utime(path, (stamp, stamp))


@pytest.fixture
def receipt_dir(tmp_path, monkeypatch):
    """Point the receipt dir at a tmp dir for the duration of the test."""
    target = tmp_path / "black_box" / "house_look"
    monkeypatch.setattr(
        house_look_tool, "DEFAULT_DATA_ROOT", str(tmp_path)
    )
    return target


def test_keep_constant_is_50() -> None:
    assert HOUSE_LOOK_RECEIPT_KEEP == 50


def test_prune_keeps_newest_50(receipt_dir) -> None:
    receipt_dir.mkdir(parents=True, exist_ok=True)
    _fake_receipts(55)
    _prune_receipts()
    remaining = sorted(p.name for p in receipt_dir.glob("look-*.jsonl"))
    assert len(remaining) == HOUSE_LOOK_RECEIPT_KEEP
    # The newest 50 survive (fake-0005 .. fake-0054); oldest five gone.
    assert remaining[0] == "look-fake-0005.jsonl"
    assert remaining[-1] == "look-fake-0054.jsonl"
    assert "look-fake-0000.jsonl" not in remaining


def test_write_receipt_triggers_prune(receipt_dir) -> None:
    receipt_dir.mkdir(parents=True, exist_ok=True)
    _fake_receipts(55)
    _write_receipt(run_id="fresh-look", action="screen_latest", ok=True)
    remaining = sorted(p.name for p in receipt_dir.glob("look-*.jsonl"))
    assert len(remaining) == HOUSE_LOOK_RECEIPT_KEEP
    assert "look-fresh-look.jsonl" in remaining  # the new receipt survives
    assert "look-fake-0000.jsonl" not in remaining


def test_write_receipt_under_limit_prunes_nothing(receipt_dir) -> None:
    receipt_dir.mkdir(parents=True, exist_ok=True)
    _fake_receipts(10)
    _write_receipt(run_id="small-look", action="cam", ok=True)
    remaining = sorted(p.name for p in receipt_dir.glob("look-*.jsonl"))
    assert len(remaining) == 11  # 10 fakes + the new receipt, nothing pruned


def test_prune_ignores_missing_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        house_look_tool, "DEFAULT_DATA_ROOT", str(tmp_path / "absent")
    )
    _prune_receipts()  # must not raise
    assert not (tmp_path / "absent").exists()


def test_prune_ignores_non_receipt_files(receipt_dir) -> None:
    receipt_dir.mkdir(parents=True, exist_ok=True)
    _fake_receipts(55)
    (receipt_dir / "notes.txt").write_text("keep me", encoding="utf-8")
    _prune_receipts()
    assert (receipt_dir / "notes.txt").exists()
    assert len(list(receipt_dir.glob("look-*.jsonl"))) == HOUSE_LOOK_RECEIPT_KEEP


def test_receipt_json_shape_unchanged(receipt_dir) -> None:
    receipt_dir.mkdir(parents=True, exist_ok=True)
    _write_receipt(run_id="shape-look", action="screen_fresh", ok=False)
    receipt = receipt_dir / "look-shape-look.jsonl"
    assert receipt.exists()
    text = receipt.read_text(encoding="utf-8").strip()
    assert text.startswith("{") and text.endswith("}")
    assert '"kind": "house_look"' in text
    assert '"run_id": "shape-look"' in text
    assert '"action": "screen_fresh"' in text
    assert '"ok": false' in text
