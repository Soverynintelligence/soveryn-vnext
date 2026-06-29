"""Deterministic materiality detector for Aetheria's heartbeat.

Pure functions only — no wall-clock, no DB access. All inputs are
pre-fetched by _gather_material_signals in daemon.py and injected here.

Constants are marked `# tune` — adjust thresholds without touching the
detection logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

# ── Tunable thresholds ────────────────────────────────────────────────────────

MATERIAL_DEADLINE_DAYS = 7  # tune
MATERIAL_STALL_HOURS = 48   # tune
MATERIAL_ERROR_TOKENS = (   # tune
    "500",
    "403",
    "404",
    "ConnectionTimeout",
    "FAILED",
)


# ── Output type ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class MaterialSignal:
    """A single material item surfaced by the detector.

    kind: "deadline" | "failure" | "stall"
    ref:  node id, title, or agent name — the hook for Task 5 prompt wiring
    detail: human-readable description, e.g. "NC Incentive due in 2 days"
    """
    kind: str
    ref: str
    detail: str


# ── Pure detector ─────────────────────────────────────────────────────────────

def detect_materiality(
    *,
    dated_items: list[dict[str, Any]],
    error_items: list[dict[str, Any]],
    stall_items: list[dict[str, Any]],
    now: datetime,
) -> list[MaterialSignal]:
    """Return every MaterialSignal that crosses a materiality threshold.

    Input shapes (dicts — tolerant of extra keys):
      dated_items: [{"ref": str, "detail": str, "date": datetime}, ...]
      error_items: [{"ref": str, "text": str}, ...]
      stall_items: [{"ref": str, "status": str, "age_hours": float}, ...]

    Deterministic: `now` is injected; no wall-clock inside.
    """
    results: list[MaterialSignal] = []

    # ── Deadlines ────────────────────────────────────────────────────────────
    for item in dated_items:
        date: datetime = item["date"]
        if date < now:
            # Past — don't surface as upcoming deadline
            continue
        days_away = (date - now).days
        if days_away <= MATERIAL_DEADLINE_DAYS:
            results.append(MaterialSignal(
                kind="deadline",
                ref=item["ref"],
                detail=f"{item['detail']} due in {days_away} day{'s' if days_away != 1 else ''}",
            ))

    # ── Failures / error tokens ───────────────────────────────────────────────
    for item in error_items:
        text: str = item.get("text", "")
        for token in MATERIAL_ERROR_TOKENS:
            if token in text:
                results.append(MaterialSignal(
                    kind="failure",
                    ref=item["ref"],
                    detail=f"error token '{token}' in: {text[:120]}",
                ))
                break  # one signal per item, first matching token wins

    # ── Stalls ────────────────────────────────────────────────────────────────
    for item in stall_items:
        if item.get("status") in ("Open", "Refining"):
            age: float = item.get("age_hours", 0)
            if age > MATERIAL_STALL_HOURS:
                results.append(MaterialSignal(
                    kind="stall",
                    ref=item["ref"],
                    detail=(
                        f"status={item['status']} for "
                        f"{int(age)}h (threshold={MATERIAL_STALL_HOURS}h)"
                    ),
                ))

    return results
