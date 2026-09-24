"""ActTruth soft lessons — learn from repeated tool mistakes.

Does not hard-block tools (v0). After the same failure pattern repeats,
surface a LESSON in prelude / tool results so the agent cannot pretend
the next identical retry will magically work.

This is the anti-loop layer: visibility (step 1) + memory of pain (step 2).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

# get_acttruth: late-imported from acttruth.audit
from acttruth.ledger import LedgerEvent

def _at():
    """Resolve ActTruth handle (late import so hosts can patch acttruth.audit.get_acttruth)."""
    from acttruth.audit import get_acttruth
    return get_acttruth()


# Soft threshold: two of the same pattern in the window → lesson.
DEFAULT_STREAK = 2
DEFAULT_WINDOW_HOURS = 6.0
DEFAULT_LOOKBACK = 40


def classify_error(error: str | None, result: Any = None) -> str:
    """Coarse error class so 'timeout after 180s' and 'timeout after 300s' match."""
    blob = (error or "").strip()
    if isinstance(result, dict):
        blob = f"{blob} {result.get('error', '')} {result.get('message', '')}"
    low = blob.lower()
    if not low:
        return "unknown"
    if "timeout" in low or "timed out" in low:
        return "timeout"
    if "toolargerror" in low or "validation" in low or "must be" in low:
        return "bad_args"
    if "unreachable" in low or "connection refused" in low or "connect" in low:
        return "unreachable"
    if "permission" in low or "denied" in low or "blocked" in low:
        return "permission"
    if "not found" in low or "missing" in low or "no such" in low:
        return "not_found"
    if "oom" in low or "out of memory" in low:
        return "oom"
    # first token-ish of error type
    m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)", blob)
    if m:
        return m.group(1).lower()[:40]
    return "error"


def pattern_key(tool: str | None, error_class: str) -> str:
    return f"{(tool or 'unknown').strip().lower()}::{error_class}"


@dataclass(frozen=True)
class Lesson:
    tool: str
    error_class: str
    streak: int
    last_summary: str
    pattern: str

    def as_block_line(self) -> str:
        return (
            f"- LESSON: `{self.tool}` failed {self.streak}× as `{self.error_class}`. "
            f"Do NOT repeat the same call hoping it works. "
            f"Change args/approach, use a different tool, or tell Jon it failed. "
            f"Last: {self.last_summary[:140]}"
        )


def lessons_from_events(
    events: list[LedgerEvent],
    *,
    streak: int = DEFAULT_STREAK,
) -> list[Lesson]:
    """Find FAIL patterns that hit the streak threshold (most recent first)."""
    fails = [e for e in events if not e.ok and e.kind in ("tool_error", "timeout")]
    counts: Counter[str] = Counter()
    latest: dict[str, LedgerEvent] = {}
    # events are newest-first
    for e in fails:
        cls = "timeout" if e.kind == "timeout" else classify_error(e.summary)
        # try to parse class from summary "tool FAILED — TimeoutError: ..."
        if "timeout" in (e.summary or "").lower():
            cls = "timeout"
        key = pattern_key(e.tool, cls)
        counts[key] += 1
        latest.setdefault(key, e)

    out: list[Lesson] = []
    for key, n in counts.most_common():
        if n < streak:
            continue
        tool, _, err_cls = key.partition("::")
        ev = latest[key]
        out.append(
            Lesson(
                tool=tool,
                error_class=err_cls,
                streak=n,
                last_summary=ev.summary,
                pattern=key,
            )
        )
    return out


def lessons_brief(
    agent_id: str,
    *,
    streak: int = DEFAULT_STREAK,
    window_hours: float = DEFAULT_WINDOW_HOURS,
    lookback: int = DEFAULT_LOOKBACK,
    max_chars: int = 700,
) -> str:
    """Prelude block. Empty if no repeat failures."""
    try:
        store = _at().ledger
        since = datetime.now() - timedelta(hours=window_hours)
        events = store.recent(agent_id, limit=lookback, since=since, failures_only=True)
        lessons = lessons_from_events(events, streak=streak)
    except Exception:
        return ""
    if not lessons:
        return ""
    lines = [
        "[ACTTRUTH LESSONS — stop repeating failures]",
        *(L.as_block_line() for L in lessons[:5]),
        "[/ACTTRUTH LESSONS]",
    ]
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + "…"
    return text


def maybe_lesson_for_tool_result(
    agent_id: str,
    *,
    tool: str,
    ok: bool,
    error: str | None = None,
    result: Any = None,
) -> str | None:
    """If this failure continues a streak, return a short lesson string for the tool payload."""
    if ok and not (isinstance(result, dict) and result.get("error")):
        return None
    err = error
    if not err and isinstance(result, dict):
        err = str(result.get("message") or result.get("error") or "")
    cls = classify_error(err, result)
    if cls == "timeout" or (error and "timeout" in error.lower()):
        cls = "timeout"
    key = pattern_key(tool, cls)
    try:
        events = _at().ledger.recent(
            agent_id,
            limit=DEFAULT_LOOKBACK,
            since=datetime.now() - timedelta(hours=DEFAULT_WINDOW_HOURS),
            failures_only=True,
        )
        # include the failure we just recorded (may already be in ledger)
        n = 0
        last_summary = err or "failed"
        for e in events:
            ecls = "timeout" if e.kind == "timeout" else classify_error(e.summary)
            if "timeout" in (e.summary or "").lower():
                ecls = "timeout"
            if pattern_key(e.tool, ecls) == key:
                n += 1
                if n == 1:
                    last_summary = e.summary
        if n < DEFAULT_STREAK:
            return None
        lesson = Lesson(
            tool=tool,
            error_class=cls,
            streak=n,
            last_summary=last_summary,
            pattern=key,
        )
        # Persist once per streak crossing (best-effort)
        if n == DEFAULT_STREAK:
            try:
                _at().ledger.record(
                    agent_id=agent_id,
                    kind="note",
                    summary=f"lesson armed: {key} streak={n}",
                    ok=True,
                    tool=tool,
                    tags=("lesson", "anti_loop", key),
                )
            except Exception:
                pass
        return lesson.as_block_line().lstrip("- ")
    except Exception:
        return None
