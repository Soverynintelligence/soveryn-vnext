"""Black-box retention sweep tests — newest KEEP per seat, nothing else."""
from __future__ import annotations

import os
import time
from pathlib import Path

from soveryn.platform.blackbox_retention import prune_blackbox, prune_seat


def _mk(dir_path, name, age_minutes=0):
    dir_path.mkdir(parents=True, exist_ok=True)
    p = dir_path / name
    p.write_text("{}\n", encoding="utf-8")
    stamp = time.time() - age_minutes * 60
    os.utime(p, (stamp, stamp))
    return p


def test_prune_seat_keeps_newest(tmp_path):
    seat = tmp_path / "kernel"
    for i in range(10):
        _mk(seat, f"cli-{i:04d}.jsonl", age_minutes=100 - i)
    removed = prune_seat(seat, keep=3)
    assert removed == 7
    remaining = sorted(p.name for p in seat.glob("*.jsonl"))
    assert remaining == ["cli-0007.jsonl", "cli-0008.jsonl", "cli-0009.jsonl"]


def test_prune_never_touches_non_receipt_files(tmp_path):
    seat = tmp_path / "kernel"
    _mk(seat, "notes.txt", age_minutes=999)
    _mk(seat, "state.json", age_minutes=999)
    _mk(seat, "cli-1.jsonl")
    assert prune_seat(seat, keep=5) == 0
    assert (seat / "notes.txt").exists() and (seat / "state.json").exists()


def test_sweep_covers_seats_and_skips_missing(tmp_path):
    bb = tmp_path / "black_box"
    for seat, n in (("aetheria", 6), ("kernel", 2)):
        for i in range(n):
            _mk(bb / seat, f"run-{i:04d}.jsonl", age_minutes=50 - i)
    removed = prune_blackbox(bb, keep=3)
    assert removed == {"aetheria": 3, "kernel": 0}
    assert prune_blackbox(bb / "absent", keep=3) == {}


def test_locked_file_survives_to_next_sweep(tmp_path, monkeypatch):
    seat = tmp_path / "kernel"
    victim = _mk(seat, "cli-old.jsonl", age_minutes=999)
    real_unlink = Path.unlink

    def refusing(self, *a, **kw):
        if self.name == victim.name:
            raise OSError("locked")
        return real_unlink(self, *a, **kw)

    monkeypatch.setattr("pathlib.Path.unlink", refusing)
    assert prune_seat(seat, keep=0) == 0  # best-effort: no raise
    assert victim.exists()
