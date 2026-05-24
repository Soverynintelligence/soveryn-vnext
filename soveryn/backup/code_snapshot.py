"""SOVERYN vNext — working-tree snapshotter.

Snapshots the vNext repo (including untracked files + __pycache__) to a
destination directory using rsync --link-dest for incremental hardlinks
when available. Atomic via .partial → rename.

The point is to survive `git reset --hard` and friends: anything on disk
in the source repo, tracked or not, gets snapshotted. Old daily backup.sh
explicitly skipped code; this fills that gap for vNext.
"""

from __future__ import annotations
import json
import os
import shutil
import socket
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


TOOL_VERSION = "0.1.0"
METADATA_FILENAME = "SNAPSHOT.json"
PARTIAL_SUFFIX = ".partial"

#: Conservative excludes — never the things git would track, only ephemeral caches
#: and our own aborted-snapshot markers. NORMAL .pyc and __pycache__ stay included
#: because that's the bytecode evidence that saved us last time.
DEFAULT_EXCLUDES: tuple[str, ...] = (
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    "*.pyc.tmp",
    f"*{PARTIAL_SUFFIX}/",
)


@dataclass(frozen=True)
class SnapshotResult:
    """Outcome of one snapshot run."""
    snapshot_dir: Path                  # final promoted dir
    file_count: int
    byte_count: int
    link_dest: Path | None              # previous snapshot used (or None)
    used_rsync: bool
    git_head: str | None
    timestamp_utc: str


def _find_previous_snapshot(dest_root: Path) -> Path | None:
    """Return the most recent finalised snapshot dir under dest_root, or None.

    Only considers directories matching YYYY-MM-DD that are NOT .partial.
    Used as the rsync --link-dest source.
    """
    if not dest_root.exists():
        return None
    candidates: list[Path] = []
    for child in dest_root.iterdir():
        if not child.is_dir():
            continue
        if child.name.endswith(PARTIAL_SUFFIX):
            continue
        # Sanity: name should look like YYYY-MM-DD or YYYY-MM-DD_HHMMSS
        if len(child.name) >= 10 and child.name[4] == "-" and child.name[7] == "-":
            candidates.append(child)
    if not candidates:
        return None
    return sorted(candidates)[-1]


def _read_git_head(repo: Path) -> str | None:
    """Read .git/HEAD directly. No subprocess. Returns trimmed content or None."""
    head_path = repo / ".git" / "HEAD"
    if not head_path.is_file():
        return None
    try:
        return head_path.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        return None


def _generate_snapshot_name(now: datetime | None = None) -> str:
    """YYYY-MM-DD if first run that day; else YYYY-MM-DD_HHMMSS to disambiguate.

    Caller decides which form; here we always return YYYY-MM-DD. The caller
    then checks for collisions and switches to the time-suffixed form.
    """
    now = now or datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%d")


def _resolve_snapshot_paths(dest_root: Path, now: datetime | None = None) -> tuple[Path, Path]:
    """Return (partial_dir, final_dir) without creating them. Disambiguates
    if a same-named finalised snapshot already exists."""
    now = now or datetime.now(timezone.utc)
    base = now.strftime("%Y-%m-%d")
    final = dest_root / base
    if final.exists():
        # Already snapshotted today — append HHMMSS to avoid clobber.
        base = now.strftime("%Y-%m-%d_%H%M%S")
        final = dest_root / base
    partial = dest_root / f"{base}{PARTIAL_SUFFIX}"
    return partial, final


def _count_files_and_bytes(root: Path, skip_filename: str | None = None) -> tuple[int, int]:
    """Walk a directory, counting files and total bytes. Skips one named file
    (the metadata file itself, so its count isn't recursive)."""
    file_count = 0
    byte_count = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for fname in filenames:
            if skip_filename and fname == skip_filename:
                continue
            try:
                byte_count += (Path(dirpath) / fname).stat().st_size
                file_count += 1
            except OSError:
                # Race: file disappeared between walk and stat. Skip silently.
                pass
    return file_count, byte_count


def _run_rsync(
    source: Path,
    dest_partial: Path,
    excludes: tuple[str, ...],
    link_dest: Path | None,
) -> None:
    """rsync -a --delete with optional --link-dest. Raises CalledProcessError on failure."""
    cmd: list[str] = ["rsync", "-a", "--delete"]
    for e in excludes:
        cmd.extend(["--exclude", e])
    if link_dest is not None:
        cmd.extend(["--link-dest", str(link_dest.resolve())])
    # Trailing slash on source = copy CONTENTS into dest, not source itself as subdir
    cmd.append(str(source.resolve()) + "/")
    cmd.append(str(dest_partial))
    subprocess.run(cmd, check=True, capture_output=True)


def _shutil_copy_fallback(
    source: Path,
    dest_partial: Path,
    excludes: tuple[str, ...],
) -> None:
    """Fallback when rsync isn't installed. Full-copy (no hardlinks)."""
    def _ignore(directory, names):
        # shutil's ignore callback gets a flat list of names per dir.
        # Match against our exclude patterns by suffix/glob style.
        from fnmatch import fnmatch
        skip: list[str] = []
        for name in names:
            for pattern in excludes:
                # Normalise pattern: trailing slash → match dir name itself
                pat = pattern.rstrip("/")
                if fnmatch(name, pat):
                    skip.append(name)
                    break
        return skip
    shutil.copytree(source, dest_partial, ignore=_ignore, dirs_exist_ok=False, symlinks=True)


def snapshot_repo(
    repo: Path,
    dest_root: Path,
    *,
    excludes: tuple[str, ...] = DEFAULT_EXCLUDES,
    now: datetime | None = None,
    rsync_available: bool | None = None,
) -> SnapshotResult:
    """Take one atomic snapshot of `repo` under `dest_root`.

    Steps:
      1. Pick partial + final paths (timestamp-based; collision → time-suffixed)
      2. Find previous snapshot (most recent finalised dir) for --link-dest
      3. rsync into <partial>/  (or shutil.copytree fallback)
      4. Write SNAPSHOT.json in <partial>/
      5. rename <partial>/ → <final>/  (atomic on same filesystem)

    Aborted runs leave <partial>/ for inspection; the next run's rotation
    leaves it alone.
    """
    repo = Path(repo).resolve()
    dest_root = Path(dest_root).resolve()
    if not repo.is_dir():
        raise FileNotFoundError(f"source repo not found: {repo}")
    dest_root.mkdir(parents=True, exist_ok=True)

    now_dt = now or datetime.now(timezone.utc)
    partial_dir, final_dir = _resolve_snapshot_paths(dest_root, now_dt)
    if partial_dir.exists():
        raise RuntimeError(
            f"prior .partial dir exists at {partial_dir} — "
            "inspect and remove before retrying"
        )

    link_dest = _find_previous_snapshot(dest_root)
    use_rsync = rsync_available if rsync_available is not None else bool(shutil.which("rsync"))

    if use_rsync:
        _run_rsync(repo, partial_dir, excludes, link_dest)
    else:
        _shutil_copy_fallback(repo, partial_dir, excludes)

    git_head = _read_git_head(repo)
    file_count, byte_count = _count_files_and_bytes(partial_dir, skip_filename=METADATA_FILENAME)

    metadata = {
        "timestamp": now_dt.isoformat(),
        "source_path": str(repo),
        "hostname": socket.gethostname(),
        "tool_version": TOOL_VERSION,
        "file_count": file_count,
        "byte_count": byte_count,
        "excludes": list(excludes),
        "link_dest": str(link_dest) if link_dest is not None else None,
        "git_head": git_head,
    }
    (partial_dir / METADATA_FILENAME).write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Atomic promote — same filesystem assumed
    os.rename(partial_dir, final_dir)

    return SnapshotResult(
        snapshot_dir=final_dir,
        file_count=file_count,
        byte_count=byte_count,
        link_dest=link_dest,
        used_rsync=use_rsync,
        git_head=git_head,
        timestamp_utc=metadata["timestamp"],
    )
