#!/usr/bin/env python
"""Find readers pointed at channels nobody writes to any more.

    python scripts/stale_readers.py            # human report
    python scripts/stale_readers.py --json     # machine-readable
    python scripts/stale_readers.py --max-age 5

This is the CLI face of the Ares observability lane, which runs the same check on
every scan and files a WARNING finding to the bus. The channel registry and the
detection live in soveryn/agents/ares/lanes/observability.py — this script
imports them rather than keeping a copy, because a duplicated registry would
drift out of sync, which is precisely the bug class being detected.

See that module for why this exists (the 18-day-silent Comms Bus).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from soveryn.agents.ares.lanes.observability import (  # noqa: E402
    DEFAULT_MAX_AGE_DAYS,
    survey_channels,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-age", type=float, default=DEFAULT_MAX_AGE_DAYS,
                    help="days of silence before a channel is flagged")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    now = datetime.now()
    results = survey_channels(now=now, max_age_days=args.max_age)

    if args.json:
        print(json.dumps({"checked_at": now.isoformat(timespec="seconds"),
                          "max_age_days": args.max_age,
                          "channels": results}, indent=2))
        return 1 if any(r["stale"] for r in results) else 0

    print(f"  channels checked: {len(results)}   "
          f"flagging anything dry > {args.max_age:g}d\n")
    for r in sorted(results, key=lambda x: (x["age_days"] is None,
                                            -(x["age_days"] or 0))):
        if r["error"]:
            mark, detail = "ERR ", r["error"][:44]
        elif r["age_days"] is None:
            mark = "NONE" if r["stale"] else "    "
            detail = ("no rows at all" if r["stale"]
                      else "empty - expected for this channel")
        else:
            mark = "DRY " if r["stale"] else "ok  "
            detail = f"{r['age_days']:>6.1f}d ago   {r['last_activity'][:19]}"
        print(f"  {mark} {r['reader']:<44} {detail}")

    stale = [r for r in results if r["stale"]]
    if stale:
        print(f"\n  {len(stale)} channel(s) dry. Each is a QUESTION, not a verdict:")
        print("  either nobody writes there any more and the reader should be")
        print("  repointed, or it has genuinely been quiet. The Comms Bus sat")
        print("  18 days on the wrong answer to exactly this question.")
    else:
        print("\n  every reader is pointed at a channel with recent traffic.")
    return 1 if stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
