"""Markdown routine docs for automations (Rakazo-inspired).

Each automation has a readable how/when/verify doc. Shipped defaults live
next to the package; Jon can override by writing the same filename under
``$SOVERYN_DATA_ROOT/automations/routines/<id>.md`` (data overlay wins).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional


_PACKAGE_ROUTINES = Path(__file__).resolve().parent / "routines"


def _data_root() -> Path:
    raw = os.environ.get("SOVERYN_DATA_ROOT")
    if raw:
        return Path(raw)
    from soveryn.config.loader import DEFAULT_DATA_ROOT

    return Path(DEFAULT_DATA_ROOT)


def overlay_dir(data_root: Path | None = None) -> Path:
    root = Path(data_root) if data_root is not None else _data_root()
    return root / "automations" / "routines"


def package_dir() -> Path:
    return _PACKAGE_ROUTINES


def routine_path(
    automation_id: str,
    *,
    data_root: Path | None = None,
) -> Optional[Path]:
    """Resolve the markdown path for one automation (overlay > package)."""
    aid = str(automation_id).strip()
    if not aid or "/" in aid or "\\" in aid or ".." in aid:
        return None
    name = f"{aid}.md"
    overlay = overlay_dir(data_root) / name
    if overlay.is_file():
        return overlay
    bundled = package_dir() / name
    if bundled.is_file():
        return bundled
    return None


def load_routine(
    automation_id: str,
    *,
    data_root: Path | None = None,
) -> Optional[Dict[str, Any]]:
    """Load one routine doc. Returns None if missing."""
    path = routine_path(automation_id, data_root=data_root)
    if path is None:
        return None
    try:
        body = path.read_text(encoding="utf-8")
    except OSError:
        return None
    source = "overlay" if path.parent == overlay_dir(data_root) else "package"
    return {
        "id": automation_id,
        "path": str(path),
        "source": source,
        "markdown": body,
        "bytes": len(body.encode("utf-8")),
    }


def routine_summary(
    automation_id: str,
    *,
    data_root: Path | None = None,
) -> Dict[str, Any]:
    """Compact flag for list endpoints — no full markdown body."""
    path = routine_path(automation_id, data_root=data_root)
    if path is None:
        return {"has_routine": False, "routine_source": None}
    source = "overlay" if path.parent == overlay_dir(data_root) else "package"
    return {"has_routine": True, "routine_source": source}
