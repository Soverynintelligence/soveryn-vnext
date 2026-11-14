#!/usr/bin/env python
"""Weekly Pondwright chat digest — who talked, who was captured, who slipped.

Reads the visitor conversation log on the Spark over SSH (read-only), filters
out test/probe/internal sessions, groups into sessions per (ip, day), and
appends a human-readable digest to data/pondwright/digest/ plus alerts only
when something needs eyes: a captured lead the CRM watch may have missed, or
an engaged multi-turn session (>=4 turns) that slipped without contact info.

Output file: data/pondwright/digest/pondwright-digest-<isoweek>.txt
"""
from __future__ import annotations

import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "data/pondwright/digest"
ALERT = REPO / "scripts/alert_signal.sh"

SSH_TARGET = "spark"
LOG_PATH = "/home/soverynspark/pondwright-agent/conversations.log"

# Session-id prefixes and log markers that are not real visitors.
SKIP_MARKERS = ("zz-", "test", "web-attr", "web-down", "ops-", "surface",
                "probe", "smoke", "admin", "127.0.0.1")
ENGAGED_TURNS = 4


def _alert(msg: str) -> None:
    if ALERT.exists():
        try:
            subprocess.run([str(ALERT), f"Pondwright digest: {msg}"],
                           timeout=30, check=False)
        except Exception:
            pass


def _fetch_log() -> list[dict]:
    """Pull the conversation log from the Spark, excluding health probes."""
    remote = (
        f"grep -v 'surface-probe' {LOG_PATH} 2>/dev/null || true"
    )
    r = subprocess.run(
        ["ssh", "-o", "ConnectTimeout=15", SSH_TARGET, remote],
        capture_output=True, text=True, timeout=60,
    )
    rows = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _is_real(d: dict) -> bool:
    s = str(d.get("session") or "").lower()
    ip = str(d.get("ip") or "")
    return not any(m in s for m in SKIP_MARKERS) and ip != "127.0.0.1"


def main() -> int:
    now = datetime.now(timezone.utc)
    year, week, _ = now.isocalendar()
    rows = [d for d in _fetch_log() if _is_real(d)]

    # Group: session id when present, else (ip, day).
    sessions: dict[str, list[dict]] = defaultdict(list)
    for d in rows:
        sid = str(d.get("session") or "").strip()
        key = sid or f"{d.get('ip')}@{str(d.get('ts'))[:10]}"
        sessions[key].append(d)

    lines = [
        f"Pondwright weekly digest — ISO week {year}-W{week}",
        f"generated {now.strftime('%Y-%m-%d %H:%M UTC')}",
        f"real turns: {len(rows)}   sessions: {len(sessions)}",
        "",
    ]
    captured, slipped = [], []

    for key, turns in sorted(
        sessions.items(), key=lambda kv: str(kv[1][0].get("ts")),
    ):
        first, last = turns[0], turns[-1]
        day = str(first.get("ts"))[:10]
        ip = str(first.get("ip") or "?")
        q1 = str(first.get("last_user"))[:80]
        did_capture = any(t.get("captured") for t in turns)
        engaged = len(turns) >= ENGAGED_TURNS
        tag = "CAPTURED" if did_capture else ("ENGAGED-SLIP" if engaged else "browsed")
        lines.append(
            f"[{day}] {key[:24]} ip={ip} turns={len(turns)} -> {tag}"
        )
        lines.append(f"    opened: {q1}")
        lines.append(f"    closed: {str(last.get('last_user'))[:80]}")
        lines.append("")
        if did_capture:
            captured.append((day, key))
        elif engaged:
            slipped.append((day, key, q1))

    if slipped:
        lines.append("ENGAGED BUT NO CONTACT INFO (worth a look):")
        for day, key, q1 in slipped:
            lines.append(f"  {day} {key[:24]} — started with: {q1}")
        lines.append("")

    lines.append(f"captured sessions this log window: {len(captured)}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"pondwright-digest-{year}-W{week:02d}.txt"
    out.write_text("\n".join(lines) + "\n")
    print(f"wrote {out}")
    print("\n".join(lines[-8:]))

    if slipped:
        _alert(
            f"{len(slipped)} engaged chat session(s) this week with no contact "
            f"info — digest: {out.name}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
