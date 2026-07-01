#!/usr/bin/env python3
"""Steward funding board — prints the deadline timeline from data/steward/grants.json.

Usage:
    python scripts/steward_board.py            # next 400 days
    python scripts/steward_board.py --days 60  # next 60 days
    python scripts/steward_board.py --award LONGVIEW-DMF-2026   # one award's detail

No app/daemon needed — reads the config directly through the Steward engine.
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from soveryn.platform.steward.store import load_grants
from soveryn.platform.steward.engine import compute_grant_schedule

CONFIG = Path(__file__).resolve().parent.parent / "data" / "steward" / "grants.json"


def main() -> None:
    ap = argparse.ArgumentParser(description="Steward funding board")
    ap.add_argument("--days", type=int, default=400, help="horizon window in days (default 400)")
    ap.add_argument("--award", type=str, default=None, help="show only this award_id")
    args = ap.parse_args()

    grants = load_grants(str(CONFIG))
    if args.award:
        grants = [g for g in grants if g.award_id == args.award]
        if not grants:
            print(f"no award_id matching {args.award!r}")
            return

    today = date.today()
    obs = compute_grant_schedule(grants, today=today, lookback_days=365, horizon_days=args.days)

    print(f"\n  STEWARD — SOVERYN FUNDING BOARD   (as of {today}, next {args.days} days)")
    print("  " + "-" * 92)
    if not obs:
        print("  (nothing in window)")
    for o in obs:
        days = (o.due_date - today).days
        when = "TODAY" if days == 0 else f"{days:+d}d"
        flag = "OVERDUE" if o.status == "overdue" else "open"
        print(f"  {o.due_date}  {when:>7}  [{flag:7}]  {o.funder[:24]:24}  {o.report_label[:50]}")
    print("  " + "-" * 92)
    print(f"  {len(grants)} funding entries tracked.  Edit data/steward/grants.json to add/update.\n")


if __name__ == "__main__":
    main()
