"""House clock — now, next house events, and upcoming timers in one view.

Every citizen session can call this instead of guessing the date or paging
through systemd. Calendar events come from docs/ops/HOUSE-CALENDAR.md so
there is exactly one source a human can edit.

Usage:
  python -m soveryn.platform.house_clock            # human view
  python -m soveryn.platform.house_clock --json     # for agents
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CALENDAR = REPO / "docs" / "ops" / "HOUSE-CALENDAR.md"
_DATE_LINE = re.compile(r"^- (\d{4}-\d{2}-\d{2}) — (.+)$")


def now() -> datetime:
    return datetime.now().astimezone()


def house_events(*, days: int = 45) -> list[dict[str, str]]:
    """Dated items from the calendar within the window, sorted soonest first."""
    out: list[dict[str, str]] = []
    if CALENDAR.is_file():
        for line in CALENDAR.read_text(encoding="utf-8").splitlines():
            m = _DATE_LINE.match(line.strip())
            if not m:
                continue
            when = datetime.strptime(m.group(1), "%Y-%m-%d").astimezone()
            if 0 <= (when.date() - now().date()).days <= days:
                out.append({"date": m.group(1), "event": m.group(2).strip()})
    return sorted(out, key=lambda e: e["date"])


def upcoming_timers(*, limit: int = 6) -> list[dict[str, str]]:
    """Next firings of user systemd timers (best effort; never raises)."""
    try:
        raw = subprocess.run(
            ["systemctl", "--user", "list-timers", "--no-pager", "--all"],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except Exception:
        return []
    out: list[dict[str, str]] = []
    for line in raw.splitlines():
        if line.startswith("NEXT"):
            continue
        parts = line.split()
        if len(parts) < 6 or "ago" in line or not parts[-1].endswith(".timer"):
            continue
        out.append({"next": " ".join(parts[:3]), "left": parts[3], "unit": parts[-1]})
        if len(out) >= limit:
            break
    return out


def view(*, days: int = 45) -> dict:
    n = now()
    return {
        "now": n.isoformat(timespec="seconds"),
        "weekday": n.strftime("%A"),
        "house_events": house_events(days=days),
        "timers_next": upcoming_timers(),
    }


def _fmt(v: dict) -> str:
    lines = [f"{v['now']}  ({v['weekday']})"]
    if v["house_events"]:
        lines.append("\nHouse calendar (next 45 days):")
        for e in v["house_events"]:
            lines.append(f"  {e['date']}  {e['event']}")
    if v["timers_next"]:
        lines.append("\nTimers next:")
        for t in v["timers_next"]:
            lines.append(f"  {t['next']}  ({t['left']})  {t['unit']}")
    return "\n".join(lines)


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="house-clock")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--days", type=int, default=45)
    a = ap.parse_args(argv)
    v = view(days=a.days)
    print(json.dumps(v, indent=1) if a.json else _fmt(v))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
