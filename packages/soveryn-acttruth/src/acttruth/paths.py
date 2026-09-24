"""Default storage locations for ActTruth (stdlib only, no SOVERYN import)."""

from __future__ import annotations

import os
from pathlib import Path

# Host apps (e.g. SOVERYN) may call set_default_root() at startup.
_default_root: Path | None = None


def set_default_root(root: Path | str | None) -> None:
    """Set the process-wide default ActTruth data directory."""
    global _default_root
    _default_root = Path(root).expanduser() if root is not None else None


def get_configured_root() -> Path | None:
    return _default_root


def default_acttruth_dir(explicit: Path | str | None = None) -> Path:
    """Resolve data dir: explicit → ACTTRUTH_DIR → configured → ~/.acttruth."""
    if explicit is not None:
        return Path(explicit).expanduser()
    env = os.environ.get("ACTTRUTH_DIR", "").strip()
    if env:
        return Path(env).expanduser()
    if _default_root is not None:
        return Path(_default_root)
    return Path.home() / ".acttruth"
