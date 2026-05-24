"""SOVERYN vNext — backup daemon CLI.

  python -m soveryn.backup.daemon --once   # one snapshot + rotation, exit
  python -m soveryn.backup.daemon          # (future: loop on schedule; currently exits with error)

For now, only --once is supported. The schedule is enforced externally
by systemd timer (see systemd/soveryn-vnext-backup.timer template).
Adding an in-process scheduler would duplicate systemd's job; not worth
the complexity.
"""

from __future__ import annotations
import argparse
import shutil
import sys
from pathlib import Path

from soveryn.backup.code_snapshot import DEFAULT_EXCLUDES, snapshot_repo, SnapshotResult
from soveryn.backup.rotation import (
    list_finalised_snapshots,
    select_snapshots_for_deletion,
)


DEFAULT_REPO = Path("/home/jon-deoliveira/soveryn_vnext")
DEFAULT_DEST = Path("/media/jon-deoliveira/easystore/soveryn_vnext_code_backups")
DEFAULT_RETAIN = 14


class BackupDaemonError(RuntimeError):
    pass


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m soveryn.backup.daemon",
        description="vNext code backup — one incremental snapshot + retention prune.",
    )
    p.add_argument("--repo", type=Path, default=DEFAULT_REPO,
                   help=f"source repo to back up (default: {DEFAULT_REPO})")
    p.add_argument("--dest", type=Path, default=DEFAULT_DEST,
                   help=f"destination root (default: {DEFAULT_DEST})")
    p.add_argument("--retain", type=int, default=DEFAULT_RETAIN,
                   help=f"keep N most recent snapshots (default: {DEFAULT_RETAIN})")
    p.add_argument("--once", action="store_true",
                   help="run one snapshot + rotation and exit (the only supported mode)")
    return p


def run_once(repo: Path, dest: Path, retain: int) -> tuple[SnapshotResult, list[Path]]:
    """Take one snapshot, then prune. Returns (snapshot_result, deleted_paths)."""
    result = snapshot_repo(repo, dest, excludes=DEFAULT_EXCLUDES)
    finalised = list_finalised_snapshots(dest)
    to_delete = select_snapshots_for_deletion(
        finalised, retain=retain, just_created=result.snapshot_dir,
    )
    deleted: list[Path] = []
    for path in to_delete:
        # Defense in depth: never delete the just-created snapshot.
        if path == result.snapshot_dir:
            continue
        shutil.rmtree(path, ignore_errors=False)
        deleted.append(path)
    return result, deleted


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if not args.once:
        print("error: only --once mode is supported (use systemd timer to schedule)",
              file=sys.stderr)
        return 2
    if args.retain < 0:
        print(f"error: --retain must be >= 0 (got {args.retain})", file=sys.stderr)
        return 2
    if not args.dest.parent.exists():
        print(f"error: dest parent does not exist: {args.dest.parent}", file=sys.stderr)
        return 1
    try:
        result, deleted = run_once(args.repo, args.dest, args.retain)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        # ENOSPC and friends — abort cleanly.
        print(f"error: I/O failure: {e}", file=sys.stderr)
        return 1
    print(
        f"[backup] snapshot {result.snapshot_dir.name}: "
        f"{result.file_count} files, {result.byte_count:,} bytes, "
        f"link_dest={'yes' if result.link_dest else 'no'}, "
        f"rsync={'yes' if result.used_rsync else 'fallback'}, "
        f"pruned={len(deleted)}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
