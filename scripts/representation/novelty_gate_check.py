#!/usr/bin/env python
"""Novelty-gate tally for the representation daemon.

Approved exit criterion (Jon, 2026-11-05, via Prometheus):

    Over 7 consecutive days, >=80% of written conclusions are novel vs the
    prior 30 days, and each written conclusion has premises traceable to
    recent conversation turns.

This script MEASURES the first half from data/memory/representation_gate.jsonl
(one JSONL line per daemon tick, written by daemon._record_gate). It never
blocks anything — the verdict is reported for a human to act on.

Exit codes: 0 = pass, 1 = fail, 2 = not enough data yet.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

DB_DIR = Path("/home/jon-deoliveira/soveryn_vnext/data/memory")
GATE_LOG = DB_DIR / "representation_gate.jsonl"

WINDOW_DAYS = 7
NOVELTY_THRESHOLD = 0.80
MIN_OFFERED = 5  # a window with fewer offered conclusions can't be judged


def load_lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return out


def gate_status(lines: list[dict], today: date | None = None) -> dict:
    """Pure verdict computation. Live ticks only (dry_run lines are ignored).

    Returns dict: verdict ('pass'|'fail'|'insufficient'), novelty ratio,
    days covered, offered/written/skipped totals.
    """
    today = today or date.today()
    cutoff_start = today - timedelta(days=WINDOW_DAYS - 1)

    per_day_offered: dict[date, int] = defaultdict(int)
    per_day_written: dict[date, int] = defaultdict(int)
    for ln in lines:
        if ln.get("dry_run"):
            continue
        try:
            day = datetime.fromisoformat(ln["ts"]).date()
        except (KeyError, ValueError):
            continue
        if not (cutoff_start <= day <= today):
            continue
        offered = int(ln.get("offered", 0))
        per_day_offered[day] += offered
        per_day_written[day] += int(ln.get("written", 0))

    days_covered = len(per_day_offered)
    offered = sum(per_day_offered.values())
    written = sum(per_day_written.values())

    if offered < MIN_OFFERED or days_covered < 2:
        return {
            "verdict": "insufficient",
            "days_covered": days_covered,
            "offered": offered,
            "written": written,
            "novelty_ratio": None,
        }

    ratio = written / offered
    return {
        "verdict": "pass" if ratio >= NOVELTY_THRESHOLD else "fail",
        "days_covered": days_covered,
        "offered": offered,
        "written": written,
        "novelty_ratio": round(ratio, 4),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", type=Path, default=GATE_LOG)
    args = ap.parse_args()

    lines = load_lines(args.log)
    status = gate_status(lines)

    print(f"gate log: {args.log} ({len(lines)} lines)")
    print(f"window: last {WINDOW_DAYS} days, threshold {NOVELTY_THRESHOLD:.0%} novel")
    print(f"live ticks: {status['days_covered']} day(s) covered")
    print(f"offered: {status['offered']}  written(novel): {status['written']}")
    if status["novelty_ratio"] is not None:
        print(f"novelty: {status['novelty_ratio']:.1%}")
    print(f"VERDICT: {status['verdict']}")

    return {"pass": 0, "fail": 1, "insufficient": 2}[status["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
