"""Black-box receipt retention — one sweep across every seat (2026-09-24).

data/black_box/<seat>/ holds one JSONL receipt per run (kernel_run, diag,
aider, opencode, ...). house_look got a prune of its own the day it was born;
every other seat grows forever (audit hole #3: aetheria was at 364 files and
climbing). This sweep keeps the newest KEEP receipts per seat, never touches
non-receipt files, and never raises to the caller.

Wired into the night librarian (03:00 timer). Run standalone:
    python -m soveryn.platform.blackbox_retention [--keep 200]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT_BLACKBOX = Path.home() / "soveryn_vnext" / "data" / "black_box"
DEFAULT_KEEP = 200


def prune_seat(seat_dir: Path, *, keep: int) -> int:
    """Keep the newest `keep` *.jsonl receipts in seat_dir. Returns removed."""
    if not seat_dir.is_dir():
        return 0
    receipts = sorted(
        (p for p in seat_dir.glob("*.jsonl") if p.is_file()),
        key=lambda p: (p.stat().st_mtime_ns, p.name),
        reverse=True,
    )
    removed = 0
    for stale in receipts[keep:]:
        try:
            stale.unlink()
            removed += 1
        except OSError:
            continue  # best-effort; a locked file survives to the next sweep
    return removed


def prune_blackbox(blackbox_dir: Path = DEFAULT_BLACKBOX, *, keep: int = DEFAULT_KEEP) -> dict[str, int]:
    """Prune every seat dir under black_box. Returns {seat: removed_count}."""
    if not blackbox_dir.is_dir():
        return {}
    return {
        seat.name: prune_seat(seat, keep=keep)
        for seat in sorted(blackbox_dir.iterdir())
        if seat.is_dir()
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prune black-box receipts (newest KEEP per seat).")
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP)
    parser.add_argument("--dir", type=Path, default=DEFAULT_BLACKBOX)
    args = parser.parse_args(argv)
    removed = prune_blackbox(args.dir, keep=args.keep)
    total = sum(removed.values())
    for seat, n in removed.items():
        if n:
            print(f"{seat}: pruned {n}")
    print(f"black_box retention: {total} receipts removed (keep={args.keep})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
