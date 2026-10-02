"""Canonical checkout-root resolver.

One place to ask "where is this tree?" so defaults work on any machine, not
only when the repo lives at ``~/soveryn_vnext``. Override with ``SOVERYN_ROOT``.
"""

from __future__ import annotations

import os
from pathlib import Path


class SoverynPaths:
    """Resolve the vNext checkout root from the environment or ``__file__``."""

    ENV_VAR = "SOVERYN_ROOT"

    @staticmethod
    def root() -> Path:
        override = os.environ.get(SoverynPaths.ENV_VAR, "").strip()
        if override:
            return Path(override).expanduser().resolve()
        # soveryn/paths.py → parents[1] is the checkout root
        return Path(__file__).resolve().parents[1]

    @staticmethod
    def data() -> Path:
        return SoverynPaths.root() / "data"
