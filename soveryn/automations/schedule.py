"""Cron due detection for automations (Hermes-inspired: one fire per due window).

Missed overnight ticks do not catch-up-storm — we fire once when due and
advance last_fired_at to now. Failure streaks are recorded for CC visibility.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from croniter import croniter

from .registry import AutomationSpec, load_automations


def _data_root() -> Path:
    raw = os.environ.get("SOVERYN_DATA_ROOT")
    if raw:
        return Path(raw)
    from soveryn.config.loader import DEFAULT_DATA_ROOT

    return Path(DEFAULT_DATA_ROOT)


def state_path(data_root: Path | None = None) -> Path:
    root = Path(data_root) if data_root is not None else _data_root()
    return root / "automations" / "schedule_state.json"


def load_state(data_root: Path | None = None) -> Dict[str, Any]:
    path = state_path(data_root)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def save_state(state: Dict[str, Any], *, data_root: Path | None = None) -> None:
    path = state_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _parse_iso(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def is_due(
    cron: str,
    *,
    now: datetime,
    last_fired_at: Optional[datetime],
    first_fire_grace: timedelta = timedelta(minutes=2),
) -> bool:
    """True if the next scheduled fire after last_fired is at or before now.

    With no last_fired (fresh install / empty state): only fire if we are
    within ``first_fire_grace`` after the most recent scheduled tick — avoids
    a Hermes-style catch-up storm that would fire every catalog job at once.
    """
    try:
        if last_fired_at is None:
            itr = croniter(cron, now)
            prev = itr.get_prev(datetime)
            return (now - prev) <= first_fire_grace
        itr = croniter(cron, last_fired_at)
        nxt = itr.get_next(datetime)
        return nxt <= now
    except (ValueError, KeyError, TypeError):
        return False


def due_automations(
    *,
    now: Optional[datetime] = None,
    data_root: Path | None = None,
) -> List[AutomationSpec]:
    """Enabled catalog entries whose cron is due given schedule state."""
    now = now or datetime.now()
    state = load_state(data_root)
    catalog, order = load_automations()
    due: List[AutomationSpec] = []
    for aid in order:
        spec = catalog[aid]
        if not spec.enabled:
            continue
        entry = state.get(aid) or {}
        last = _parse_iso(entry.get("last_fired_at") if isinstance(entry, dict) else None)
        if is_due(spec.cron, now=now, last_fired_at=last):
            due.append(spec)
    return due


def record_fire(
    automation_id: str,
    *,
    status: str,
    run_id: str | None = None,
    now: Optional[datetime] = None,
    data_root: Path | None = None,
) -> Dict[str, Any]:
    """Update last_fired_at and failure_streak (Hermes-inspired)."""
    now = now or datetime.now()
    state = load_state(data_root)
    prev = state.get(automation_id) if isinstance(state.get(automation_id), dict) else {}
    streak = int(prev.get("failure_streak") or 0)
    if status == "ok":
        streak = 0
    else:
        streak += 1
    entry = {
        "last_fired_at": now.isoformat(timespec="seconds"),
        "last_status": status,
        "last_run_id": run_id,
        "failure_streak": streak,
    }
    state[automation_id] = entry
    save_state(state, data_root=data_root)
    return entry
