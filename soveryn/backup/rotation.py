"""SOVERYN vNext — backup retention policy."""

from __future__ import annotations
from pathlib import Path

from soveryn.backup.code_snapshot import PARTIAL_SUFFIX


def select_snapshots_for_deletion(
    snapshots: list[Path],
    retain: int,
    just_created: Path | None = None,
) -> list[Path]:
    """Return the snapshot dirs that should be deleted, oldest-first.

    Inputs:
      snapshots: candidate paths (typically all finalised dirs in dest_root).
                 .partial dirs SHOULD NOT be passed in.
      retain:    keep at least this many (most recent N by name-sort).
      just_created: the snapshot path that was just produced; MUST NOT be
                    in the returned list even if naming corner cases would
                    have included it (Jon constraint 9).

    Behavior:
      - Filter out .partial dirs defensively.
      - Sort by name (which is timestamp-ordered).
      - Keep the last `retain`.
      - Return the rest (the ones to delete), oldest-first.
    """
    if retain < 0:
        raise ValueError(f"retain must be >= 0 (got {retain})")
    if retain == 0:
        # Defensive: never delete just_created even with retain=0.
        candidates = [p for p in snapshots if not p.name.endswith(PARTIAL_SUFFIX)]
        candidates_sorted = sorted(candidates, key=lambda p: p.name)
        if just_created is not None:
            candidates_sorted = [p for p in candidates_sorted if p != just_created]
        return candidates_sorted

    candidates = [p for p in snapshots if not p.name.endswith(PARTIAL_SUFFIX)]
    candidates_sorted = sorted(candidates, key=lambda p: p.name)
    if len(candidates_sorted) <= retain:
        return []
    # Oldest = front; keep last `retain`; delete the rest.
    keep = set(candidates_sorted[-retain:])
    if just_created is not None:
        keep.add(just_created)  # never delete the just-created one
    to_delete = [p for p in candidates_sorted if p not in keep]
    return to_delete


def list_finalised_snapshots(dest_root: Path) -> list[Path]:
    """Return all finalised (non-.partial) snapshot dirs in dest_root."""
    if not dest_root.exists():
        return []
    out: list[Path] = []
    for child in dest_root.iterdir():
        if child.is_dir() and not child.name.endswith(PARTIAL_SUFFIX):
            # Conservative: name must look like a date
            if len(child.name) >= 10 and child.name[4] == "-" and child.name[7] == "-":
                out.append(child)
    return out
