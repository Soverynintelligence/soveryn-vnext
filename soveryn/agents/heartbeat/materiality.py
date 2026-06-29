"""Deterministic materiality detector for Aetheria's heartbeat.

Pure functions only — no wall-clock, no DB access. All inputs are
pre-fetched by _gather_material_signals in daemon.py and injected here.

Constants are marked `# tune` — adjust thresholds without touching the
detection logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
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

# ── Stall re-tune constants (T6) ─────────────────────────────────────────────

STALL_AMNESTY_HOURS = 72        # tune — amnesty window after deploy
STALL_WORST_FIRST_CAP = 3       # tune — max stalls returned post-amnesty when board is large
STALL_WORST_FIRST_TRIGGER = 5   # tune — cap only kicks in when stale count exceeds this


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


# ── Deploy clock (impure — filesystem; quarantined here) ─────────────────────

def get_deploy_started_at(path: Path | str, now: datetime) -> datetime:
    """Read-or-create the deploy-start sentinel file.

    First call: writes `now` as an ISO-8601 string and returns it.
    Subsequent calls: reads and returns the persisted timestamp unchanged.

    The sentinel file is the ONLY impure bit in the stall re-tune logic.
    All stall amnesty/cap logic in detect_materiality is pure (injected
    `hours_since_deploy`); the gather layer calls this once and injects
    the computed float.

    Args:
        path: Path to the sentinel file (e.g. data/heartbeat_deploy_started_at).
        now:  Current time — used only on first call to initialise the sentinel.

    Returns:
        The persisted deploy-start datetime (naive, no timezone).
    """
    p = Path(path)
    if p.exists():
        raw = p.read_text().strip()
        return datetime.fromisoformat(raw)
    # First call — write and return now.
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(now.isoformat())
    return now


# ── Pure detector ─────────────────────────────────────────────────────────────

def detect_materiality(
    *,
    dated_items: list[dict[str, Any]],
    error_items: list[dict[str, Any]],
    stall_items: list[dict[str, Any]],
    now: datetime,
    hours_since_deploy: float | None = None,
) -> list[MaterialSignal]:
    """Return every MaterialSignal that crosses a materiality threshold.

    Input shapes (dicts — tolerant of extra keys):
      dated_items: [{"ref": str, "detail": str, "date": datetime}, ...]
      error_items: [{"ref": str, "text": str}, ...]
      stall_items: [{"ref": str, "status": str, "age_hours": float}, ...]

    Stall lane behaviour (T6 re-tune):
      hours_since_deploy=None (default) → legacy mode: all >48h stalls flagged,
        no cap. Keeps Task 1 tests green and preserves backward compat for callers
        that don't pass the deploy clock yet.

      hours_since_deploy < STALL_AMNESTY_HOURS (72h) → amnesty window:
        only flag stalls that CROSSED 48h *during* the window.
        Formula: age_hours > 48 AND (age_hours - hours_since_deploy) < 48
        Suppresses everything already stale at deploy so the board doesn't
        immediately light up red on every pulse.

      hours_since_deploy >= STALL_AMNESTY_HOURS → post-amnesty:
        all >48h stalls flagged, BUT if count > STALL_WORST_FIRST_TRIGGER (5)
        return only the STALL_WORST_FIRST_CAP (3) oldest (sorted age desc).
        Gives Aetheria a trend signal, not a wall of red.

    Deterministic: `now` and `hours_since_deploy` are injected; no wall-clock
    or filesystem access inside this function.
    """
    results: list[MaterialSignal] = []

    # ── Deadlines ────────────────────────────────────────────────────────────
    # Normalise to date for comparison: accept both datetime and date objects
    # in item["date"] so the regex bridge (which produces date objects) and
    # any future structured-datetime path both work without special-casing.
    now_date: date = now.date() if isinstance(now, datetime) else now
    for item in dated_items:
        raw_date = item["date"]
        item_date: date = raw_date.date() if isinstance(raw_date, datetime) else raw_date
        if item_date < now_date:
            # Past — don't surface as upcoming deadline
            continue
        days_away = (item_date - now_date).days
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
    candidate_stalls: list[dict[str, Any]] = []
    for item in stall_items:
        if item.get("status") not in ("Open", "Refining"):
            continue
        age: float = item.get("age_hours", 0)
        if age <= MATERIAL_STALL_HOURS:
            # Sub-threshold — never a stall regardless of mode.
            continue

        if hours_since_deploy is None:
            # Legacy mode: no deploy clock → flag every >48h stall unchanged.
            candidate_stalls.append(item)
        elif hours_since_deploy < STALL_AMNESTY_HOURS:
            # Amnesty window: only nodes that CROSSED 48h during this window.
            # Age at deploy time = age_hours - hours_since_deploy.
            # "Crossed" means it was <48h at deploy, i.e. (age - hsd) < 48.
            age_at_deploy = age - hours_since_deploy
            if age_at_deploy < MATERIAL_STALL_HOURS:
                # Newly crossed — flag it.
                candidate_stalls.append(item)
            # else: already stale at deploy — suppress.
        else:
            # Post-amnesty: flag all >48h stalls (worst-first cap applied below).
            candidate_stalls.append(item)

    # Apply worst-first cap post-amnesty when too many stalls exist.
    # (In legacy/amnesty mode candidate_stalls may also be large, but the
    # cap only applies when hours_since_deploy >= STALL_AMNESTY_HOURS.)
    if (
        hours_since_deploy is not None
        and hours_since_deploy >= STALL_AMNESTY_HOURS
        and len(candidate_stalls) > STALL_WORST_FIRST_TRIGGER
    ):
        candidate_stalls = sorted(
            candidate_stalls,
            key=lambda x: x.get("age_hours", 0),
            reverse=True,
        )[:STALL_WORST_FIRST_CAP]

    for item in candidate_stalls:
        age = item.get("age_hours", 0)
        results.append(MaterialSignal(
            kind="stall",
            ref=item["ref"],
            detail=(
                f"status={item['status']} for "
                f"{int(age)}h (threshold={MATERIAL_STALL_HOURS}h)"
            ),
        ))

    return results
