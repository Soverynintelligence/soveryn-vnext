"""CWG lattice stale prefixes + pin."""

from __future__ import annotations

from soveryn.platform.lattice.stale_scan import PinChecklistRow

PREFIXES: dict[str, int] = {
    "cwg.job.": 60,
    "cwg.ads.": 30,
}

PINS: tuple[PinChecklistRow, ...] = (
    PinChecklistRow("cwg.ads.pmax", "paused", "live"),
)
