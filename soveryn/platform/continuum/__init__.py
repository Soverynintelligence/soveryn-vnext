"""Deprecated shim — use soveryn.platform.acttruth (ActTruth by SOVERYN)."""
from __future__ import annotations

import warnings

warnings.warn(
    "soveryn.platform.continuum is renamed to soveryn.platform.acttruth",
    DeprecationWarning,
    stacklevel=2,
)

from soveryn.platform.acttruth import *  # noqa: F403
from soveryn.platform.acttruth import __all__  # noqa: F401
