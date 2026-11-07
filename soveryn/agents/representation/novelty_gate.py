"""Representation novelty gate (LIVE, approved by Jon 2026-11-06 20:14 ET).

Rules (verbatim intent):
- Recent turns = conversation turns from the 7 days before a conclusion's own
  timestamp. A written conclusion is *traceable* when at least one premise
  `turn:<session_id>:<idx>` resolves to a real stored turn (0-based index into
  the session's full history, rowid order) whose timestamp is in
  [conclusion_ts - 7d, conclusion_ts].
- Novel = passes the existing writeback dedupe (no sha256 match of the
  normalized text, difflib ratio < 0.92) against every conclusion created in
  the 30 days before that conclusion's own timestamp. Dedupe code is reused
  unchanged from writeback.py.
- Days = completed calendar days in America/New_York.
- A day is green when it has >=1 conclusion and >=80% of its conclusions are
  BOTH novel and traceable. A day with ZERO conclusions is red (resets).
- Gate PASSES when the 7 most recent completed days are all green (streak>=7).

Measurement only: the gate never blocks writes. Pure core (`evaluate`) takes
plain data so tests need no DB.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable, Sequence
from zoneinfo import ZoneInfo

from soveryn.agents.representation.writeback import (
    _hash, _is_near_duplicate, _normalize,
)

TZ = ZoneInfo("America/New_York")
RECENT_TURN_DAYS = 7
NOVELTY_WINDOW_DAYS = 30
THRESHOLD = 0.80
STREAK_REQUIRED = 7


@dataclass(frozen=True)
class ConclusionRec:
    id: str
    content: str
    created_at: datetime  # tz-aware (America/New_York)
    premises: tuple[str, ...] = ()


@dataclass
class DayResult:
    day: date
    total: int = 0
    novel: int = 0
    traceable: int = 0
    good: int = 0  # novel AND traceable

    @property
    def ratio(self) -> float | None:
        return self.good / self.total if self.total else None

    @property
    def green(self) -> bool:
        return self.total > 0 and self.good / self.total >= THRESHOLD

    def as_dict(self) -> dict:
        return {"day": self.day.isoformat(), "total": self.total,
                "novel": self.novel, "traceable": self.traceable,
                "good": self.good,
                "ratio": None if self.ratio is None else round(self.ratio, 4),
                "green": self.green}


def to_ny(ts: str | datetime) -> datetime:
    """Parse a timestamp; naive values are box-local = America/New_York."""
    dt = datetime.fromisoformat(ts) if isinstance(ts, str) else ts
    return dt.replace(tzinfo=TZ) if dt.tzinfo is None else dt.astimezone(TZ)


TurnLookup = Callable[[str, int], "datetime | None"]


def is_novel(c: ConclusionRec, all_recs: Sequence[ConclusionRec]) -> bool:
    lo = c.created_at - timedelta(days=NOVELTY_WINDOW_DAYS)
    prior = [_normalize(o.content) for o in all_recs
             if o.id != c.id and lo <= o.created_at < c.created_at]
    norm = _normalize(c.content)
    if _hash(norm) in {_hash(p) for p in prior}:
        return False
    return not _is_near_duplicate(norm, prior)


def is_traceable(c: ConclusionRec, turn_ts: TurnLookup) -> bool:
    lo = c.created_at - timedelta(days=RECENT_TURN_DAYS)
    for p in c.premises:
        if not isinstance(p, str) or not p.startswith("turn:"):
            continue
        try:
            sid, idx = p[5:].rsplit(":", 1)
            ts = turn_ts(sid, int(idx))
        except (ValueError, TypeError):
            continue
        if ts is not None and lo <= ts <= c.created_at:
            return True
    return False


def evaluate(recs: Sequence[ConclusionRec], turn_ts: TurnLookup, *,
             today: date, lookback_days: int = 14) -> dict:
    """Per-day table for completed NY days (yesterday back `lookback_days`),
    streak of consecutive green days ending yesterday, and pass/fail."""
    last = today - timedelta(days=1)
    first = last - timedelta(days=max(lookback_days, STREAK_REQUIRED) - 1)
    days = {first + timedelta(days=i): DayResult(first + timedelta(days=i))
            for i in range((last - first).days + 1)}
    for c in recs:
        d = c.created_at.date()
        if d not in days:
            continue
        r = days[d]
        n, t = is_novel(c, recs), is_traceable(c, turn_ts)
        r.total += 1; r.novel += n; r.traceable += t; r.good += (n and t)
    streak = 0
    for d in sorted(days, reverse=True):
        if not days[d].green:
            break  # empty day or <80% day resets the streak
        streak += 1
    return {
        "evaluated_through": last.isoformat(),
        "timezone": "America/New_York",
        "days": [days[d].as_dict() for d in sorted(days)],
        "streak": streak,
        "required": STREAK_REQUIRED,
        "status": "pass" if streak >= STREAK_REQUIRED else "fail",
    }


# ─── Live adapters ──────────────────────────────────────────────────────────

def load_conclusions(lattice_db: Path, *, owner_agent: str = "aetheria") -> list[ConclusionRec]:
    con = sqlite3.connect(f"file:{lattice_db}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT id, content, created_at, provenance FROM nodes "
                           "WHERE type='conclusion' AND agent=?", (owner_agent,)).fetchall()
    finally:
        con.close()
    out = []
    for nid, content, created, prov in rows:
        try:
            prem = tuple((json.loads(prov) or {}).get("premises") or ()) if prov else ()
        except (json.JSONDecodeError, TypeError, AttributeError):
            prem = ()
        out.append(ConclusionRec(nid, content or "", to_ny(created), prem))
    return out


def conv_turn_lookup(conv_db: Path) -> TurnLookup:
    con = sqlite3.connect(f"file:{conv_db}?mode=ro", uri=True)
    cache: dict[str, list[str]] = {}

    def lookup(sid: str, idx: int) -> datetime | None:
        if sid not in cache:
            cache[sid] = [r[0] for r in con.execute(
                "SELECT timestamp FROM conversations WHERE session_id=? "
                "ORDER BY rowid ASC", (sid,))]
        rows = cache[sid]
        if not (0 <= idx < len(rows)):
            return None
        try:
            return to_ny(rows[idx])
        except (ValueError, TypeError):
            return None
    return lookup


def run_live(lattice_db: Path, conv_db: Path, *, now: datetime | None = None,
             lookback_days: int = 14, owner_agent: str = "aetheria") -> dict:
    today = to_ny(now or datetime.now(TZ)).date()
    res = evaluate(load_conclusions(lattice_db, owner_agent=owner_agent), conv_turn_lookup(conv_db),
                   today=today, lookback_days=lookback_days)
    res["owner_agent"] = owner_agent
    res["computed_at"] = datetime.now(TZ).isoformat(timespec="seconds")
    return res


def format_table(res: dict) -> str:
    lines = [f"Representation novelty gate — through {res['evaluated_through']} "
             f"({res['timezone']})",
             f"{'day':<11} {'total':>5} {'novel':>5} {'trace':>5} {'good':>5} {'ratio':>6}  green"]
    for d in res["days"]:
        r = "—" if d["ratio"] is None else f"{d['ratio']:.0%}"
        lines.append(f"{d['day']:<11} {d['total']:>5} {d['novel']:>5} "
                     f"{d['traceable']:>5} {d['good']:>5} {r:>6}  "
                     f"{'yes' if d['green'] else 'no'}")
    lines.append(f"streak: {res['streak']}/{res['required']}  STATUS: {res['status'].upper()}")
    return "\n".join(lines)
