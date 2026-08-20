"""ActTruth Step 3 — enqueue bug-triage candidates when soft lessons arm.

ActTruth sees streaks; this module parks a durable-correction *candidate*
for Vett/Scotty/skill-capture. It does not auto-fix anything.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


# Don't re-open the same pattern more than once per cooldown.
DEFAULT_COOLDOWN = timedelta(hours=6)


def _data_root() -> Path:
    raw = os.environ.get("SOVERYN_DATA_ROOT")
    if raw:
        return Path(raw)
    from soveryn.config.loader import DEFAULT_DATA_ROOT

    return Path(DEFAULT_DATA_ROOT)


def triage_path(data_root: Path | None = None) -> Path:
    root = Path(data_root) if data_root is not None else _data_root()
    return root / "acttruth" / "triage.jsonl"


def suggest_correction_type(error_class: str) -> str:
    """Heuristic only — Vett may override later."""
    cls = (error_class or "").lower()
    if cls in ("bad_args", "not_found", "validation"):
        return "skill"
    if cls in ("timeout", "unreachable", "oom"):
        return "ops"
    if cls in ("permission", "denied"):
        return "ask_jon"
    return "code"


def suggest_owner(agent: str, error_class: str, correction_type: str) -> str:
    if correction_type == "code":
        return "scotty"
    if correction_type == "ask_jon":
        return "aetheria"
    if correction_type == "ops":
        return "aetheria"
    # skill / default triage
    if agent in ("scotty", "kernel"):
        return "scotty"
    return "vett"


def _parse_iso(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _recent_open_patterns(
    path: Path,
    *,
    since: datetime,
) -> set[str]:
    """Patterns already queued (any status) since ``since`` — cooldown set."""
    if not path.is_file():
        return set()
    found: set[str] = set()
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > 256 * 1024:
                fh.seek(size - 256 * 1024)
                fh.readline()
            raw = fh.read().decode("utf-8", "replace")
    except OSError:
        return found
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict):
            continue
        ts = _parse_iso(rec.get("created_at"))
        if ts is not None and ts < since:
            continue
        pat = rec.get("pattern")
        agent = rec.get("agent")
        if pat and agent:
            found.add(f"{agent}::{pat}")
    return found


def enqueue_from_lesson(
    *,
    agent: str,
    tool: str,
    error_class: str,
    streak: int,
    pattern: str,
    summary: str,
    lesson_text: str | None = None,
    data_root: Path | None = None,
    now: datetime | None = None,
    cooldown: timedelta = DEFAULT_COOLDOWN,
) -> Optional[Dict[str, Any]]:
    """Append one triage candidate if cooldown allows. Returns the row or None."""
    now = now or datetime.now()
    path = triage_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    dedupe_key = f"{agent}::{pattern}"
    recent = _recent_open_patterns(path, since=now - cooldown)
    if dedupe_key in recent:
        return None

    correction = suggest_correction_type(error_class)
    owner = suggest_owner(agent, error_class, correction)
    record: Dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "created_at": now.isoformat(timespec="seconds"),
        "status": "open",
        "agent": agent,
        "tool": tool,
        "error_class": error_class,
        "streak": int(streak),
        "pattern": pattern,
        "summary": (summary or "")[:400],
        "lesson": (lesson_text or "")[:500],
        "correction_type": correction,
        "owner": owner,
        "source": "acttruth_lesson",
        "note": (
            "Step 3 candidate — classify then skill/code/ops. "
            "Does not auto-fix."
        ),
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")
    return record


def enqueue_if_lesson(
    *,
    agent: str,
    tool: str,
    lesson_text: str,
    error: str | None = None,
    result: Any = None,
    data_root: Path | None = None,
) -> Optional[Dict[str, Any]]:
    """House hook after ``maybe_lesson_for_tool_result`` returns a string."""
    if not lesson_text or not tool:
        return None
    from acttruth.lessons import classify_error, pattern_key

    # Recover streak from lesson text when possible ("failed N×")
    streak = 2
    try:
        import re

        m = re.search(r"failed\s+(\d+)×", lesson_text)
        if m:
            streak = int(m.group(1))
    except Exception:
        pass
    cls = classify_error(error, result)
    if error and "timeout" in error.lower():
        cls = "timeout"
    pat = pattern_key(tool, cls)
    return enqueue_from_lesson(
        agent=agent,
        tool=tool,
        error_class=cls,
        streak=streak,
        pattern=pat,
        summary=str(error or (result.get("message") if isinstance(result, dict) else "") or lesson_text)[:400],
        lesson_text=lesson_text,
        data_root=data_root,
    )


def list_triage(
    *,
    limit: int = 40,
    status: str | None = "open",
    data_root: Path | None = None,
) -> List[Dict[str, Any]]:
    """Newest-first triage rows."""
    path = triage_path(data_root)
    if not path.is_file():
        return []
    limit = max(1, min(int(limit), 200))
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > 512 * 1024:
                fh.seek(size - 512 * 1024)
                fh.readline()
            raw = fh.read().decode("utf-8", "replace")
    except OSError:
        return []
    rows: List[Dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict):
            continue
        if status and rec.get("status") != status:
            continue
        rows.append(rec)
    rows.reverse()
    return rows[:limit]
