"""Alert on the ABSENCE of a signal, not only on a bad one.

Everything else in this package answers "is it working?" This module answers a
different question that nothing in the fleet was asking: **when did we last
actually look?**

Atticus was 404 with its systemd unit never installed. That is not a failing
check — it is the absence of a check. Every monitor on this box was oriented the
same way: something reports a problem, an alert fires. Nothing fired when a
surface stopped reporting, and nothing at all fired for a surface that had
*never* reported, because from the monitor's side those look identical to
silence, and silence looked like health.

So the rule here is inverted. A surface that has never been verified is a
finding **immediately**, at the same severity as one that is failing — because
"we have no idea" and "it is broken" carry the same operational risk, and only
one of them announces itself.

The observation record is deliberately dumb: names to timestamps. It survives
restarts, it is readable by eye, and it is the ground truth for "when did we
last look," which is exactly the fact that went missing.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from soveryn.platform.surfaces.probe import Result, Status
from soveryn.platform.surfaces.registry import Surface

DEFAULT_PATH = Path.home() / "soveryn_vnext" / "data" / "surfaces" / "last_seen.json"

NEVER = "never"


@dataclass(frozen=True)
class Staleness:
    surface: str
    reason: str            # "never-verified" | "stale"
    last_healthy_at: float | None
    age_s: float | None
    interval_s: float

    @property
    def never(self) -> bool:
        return self.last_healthy_at is None


class Observations:
    """When each surface was last seen HEALTHY. Not when it was last probed.

    Storing last-probed would defeat the purpose: a surface probed every minute
    and failing every minute is fresh by that measure and broken in fact. Only a
    successful probe resets the clock.
    """

    def __init__(self, path: Path | str = DEFAULT_PATH) -> None:
        self.path = Path(path)
        self._data: dict[str, float] = {}
        self._load()

    def _load(self) -> None:
        try:
            self._data = json.loads(self.path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            self._data = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic: a truncated observation file would read as "never verified"
        # for everything and alarm the whole fleet at once.
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(self._data, fh, indent=2, sort_keys=True)
            os.replace(tmp, self.path)
        except Exception:
            os.unlink(tmp)
            raise

    def record(self, results: list[Result]) -> None:
        changed = False
        for r in results:
            if r.status is Status.HEALTHY:
                self._data[r.surface] = r.checked_at
                changed = True
        if changed:
            self._save()

    def last_healthy(self, name: str) -> float | None:
        return self._data.get(name)

    def stale(self, surfaces, *, now: float | None = None) -> list[Staleness]:
        """Surfaces overdue for a successful verification, or never verified.

        Grace is 2x the declared interval before staleness alone is reported —
        one missed cycle is a blip, two is a pattern. Never-verified gets no
        grace at all; there is nothing to be patient about.
        """
        now = time.time() if now is None else now
        out: list[Staleness] = []
        for s in surfaces:
            if s.retired:
                continue
            last = self._data.get(s.name)
            if last is None:
                out.append(Staleness(s.name, "never-verified", None, None, s.interval_s))
                continue
            age = now - last
            if age > s.interval_s * 2:
                out.append(Staleness(s.name, "stale", last, age, s.interval_s))
        return out
