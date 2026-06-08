"""Salience markers — minimal stub.

Task 2 ships the full marker categories table + detect_markers() with the
locked weight scheme. This stub exposes only MarkerHit so store.py can
import it; the package __init__ also re-exports MARKER_CATEGORIES and
detect_markers, so those names must exist as placeholders here too — but
they stay no-op until Task 2.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class MarkerHit:
    category: str
    marker: str
    weight: int


# Placeholders so `from soveryn.platform.salience import ...` works before
# Task 2 lands the real marker tables + detection logic. They are
# intentionally empty / no-op; replacing them is Task 2's job.
MARKER_CATEGORIES: tuple = ()


def detect_markers(text: str, *, role: str) -> Sequence[MarkerHit]:
    """Stub. Real implementation lands in Task 2."""
    return ()
