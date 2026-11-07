#!/usr/bin/env python
"""Representation novelty gate — live check (rules approved by Jon 2026-11-06 20:14 ET).

Reads the live lattice + conversation DBs read-only and prints the per-day
table (completed America/New_York days), the streak and PASS/FAIL. Rules live
in soveryn/agents/representation/novelty_gate.py. The daemon writes the same
result each tick to data/memory/representation_novelty_gate_status.json.

Exit codes: 0 = pass, 1 = fail.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from soveryn.agents.representation.novelty_gate import format_table, run_live  # noqa: E402

MEM = ROOT / "data" / "memory"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lattice", type=Path, default=MEM / "lattice_vnext.db")
    ap.add_argument("--conv", type=Path, default=MEM / "conversations_vnext.db")
    ap.add_argument("--days", type=int, default=14, help="completed days to show (min 7)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    res = run_live(a.lattice, a.conv, lookback_days=a.days)
    print(json.dumps(res, indent=2) if a.json else format_table(res))
    return 0 if res["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
