"""SOVERYN default ActTruth paths — configures the portable package root."""

from __future__ import annotations

from pathlib import Path

from acttruth.paths import default_acttruth_dir as _pkg_default
from acttruth.paths import set_default_root


def default_acttruth_dir(data_root: Path | None = None) -> Path:
    """SOVERYN default: <data_root>/acttruth/. Portable callers use acttruth.paths."""
    if data_root is None:
        from soveryn.config.loader import DEFAULT_DATA_ROOT

        data_root = DEFAULT_DATA_ROOT
    root = Path(data_root) / "acttruth"
    # Keep portable get_acttruth() pointed at the house ledger when SOVERYN is loaded.
    set_default_root(root)
    return root


# On import, align package default with house data root (best-effort).
try:
    default_acttruth_dir()
except Exception:
    pass

__all__ = ["default_acttruth_dir", "set_default_root", "_pkg_default"]
