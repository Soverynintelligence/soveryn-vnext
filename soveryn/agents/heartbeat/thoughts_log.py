"""Append-only JSONL pulse black box for heartbeat pulses.

Each record written by :class:`ThoughtsLog` has the shape::

    {
        "pulse_id":         str,   # unique identifier for the pulse
        "ts":               str,   # ISO-8601 wall-clock timestamp
        "snapshot":         dict,  # LOAD-BEARING — board counts + material_signals
                                   # + lattice fields captured this pulse.
                                   # compute_delta reads prev_record["snapshot"]
                                   # on the next pulse to detect board changes;
                                   # dropping or renaming this key breaks the
                                   # delta round-trip contract.
        "material_signals": list,  # signals that crossed the materiality threshold
        "delta":            dict,  # what changed relative to the previous pulse
        "decision":         str,   # SURFACE | ACCEPT_RISK | NO_OP
        "rationale":        str,   # one-line reason for the decision
        "surfaced":         bool,  # True if the pulse was promoted to Aetheria
        "violation":        str,   # OPTIONAL — present only when the daemon
                                   # detected a protocol violation (e.g. NO_OP
                                   # on material signals, or bare [SURFACE] with
                                   # empty content on material). Records the
                                   # fail-safe action taken.
    }

Records are persisted as JSONL (one JSON object per line) so the file can be
tailed, grepped, and streamed without any additional tooling.
"""

from __future__ import annotations

import json
from pathlib import Path


class ThoughtsLog:
    """Append-only JSONL log of heartbeat pulse records."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def append(self, record: dict) -> None:
        """Append *record* as a single JSON line.

        Creates the parent directory if it does not already exist (best-effort).
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def last(self) -> dict | None:
        """Return the final non-empty record, or ``None`` if absent/empty."""
        if not self._path.exists():
            return None
        with self._path.open("r", encoding="utf-8") as fh:
            lines = fh.readlines()
        for line in reversed(lines):
            stripped = line.strip()
            if stripped:
                return json.loads(stripped)
        return None

    def last_standing_note(self, *, limit: int = 64) -> str:
        """Most recent non-empty pulse note, walking back past unchanged skips.

        Unchanged skips write ``note: ""`` so they do not re-surface as
        "reflected" in Command Center; standing-note continuity still needs
        the prior real admission / reflection.
        """
        if not self._path.exists():
            return ""
        with self._path.open("r", encoding="utf-8") as fh:
            lines = fh.readlines()
        seen = 0
        for line in reversed(lines):
            stripped = line.strip()
            if not stripped:
                continue
            seen += 1
            if seen > limit:
                break
            try:
                rec = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            note = str((rec or {}).get("note") or "").strip()
            if note:
                return note
        return ""
