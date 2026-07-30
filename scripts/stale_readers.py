#!/usr/bin/env python
"""Find readers pointed at channels nobody writes to any more.

    python scripts/stale_readers.py            # human report
    python scripts/stale_readers.py --json     # machine-readable
    python scripts/stale_readers.py --max-age 30

WHY
---
2026-07-30: the Comms Bus panel had shown nothing for 18 days. Nothing was
broken and no data was missing — it read `edges WHERE relationship LIKE
'direct%'`, a channel that produced NINE rows in two months, while 537 real
agent-to-agent events flowed through coord_event_log and delegation. Delegation
had been built as its own subsystem and nobody asked what was reading the old
channel.

That is a DIFFERENT failure from the one tests/test_shared_context_wiring_contract.py
catches. That contract catches wiring that was never done. This catches wiring
that has gone stale: a reader still faithfully querying a road nobody drives on.

Both are the same root cause — a subsystem shipped without asking what elsewhere
needs to know about it — but they need different detectors, because stale wiring
looks exactly like a quiet week until you compare it against everything else.

WHAT IT CANNOT DO
-----------------
It cannot tell "orphaned" from "genuinely quiet". A dry channel is a QUESTION,
not a verdict — the answer is either "nobody uses that any more, repoint it" or
"correct, that has been quiet". The point is to be asked at all, rather than
noticing 18 days later because a panel looked empty.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from soveryn.config.loader import load_env_config  # noqa: E402

# Each entry: what reads it, and the query that answers "when did this channel
# last produce anything?". Adding a reader here is the cheap half of shipping a
# new subsystem — the half that was skipped every time this bit us.
# NOTE: tower-local stores only. The Pondwright CRM (leads.db) and the Seneca
# audit log live on the Spark and are not reachable from here — they have their
# own glance panels on mission control. A check that silently reports a remote
# service as "database missing" is worse than no check.
CHANNELS: list[dict] = [
    {"reader": "Comms Bus · legacy direct edges", "db": "lattice",
     "sql": "SELECT MAX(created_at) FROM edges WHERE relationship LIKE 'direct%'"},
    {"reader": "Comms Bus · board handoffs", "db": "lattice",
     "sql": "SELECT MAX(created_at) FROM coord_event_log "
            "WHERE triggered_agents IS NOT NULL AND triggered_agents != ''"},
    {"reader": "Comms Bus · delegation dispatches", "db": "delegation",
     "sql": "SELECT MAX(created_at) FROM delegation_tasks"},
    # allow_empty: an empty review queue is the NORMAL state — it means nothing
    # is waiting on Jon, not that the reader is broken. A detector that nags
    # about a healthy condition is one you learn to ignore, which is how the
    # audit tool's prose caveat got overridden on 2026-07-27.
    {"reader": "Scotty approvals · /api/delegation/pending", "db": "delegation",
     "sql": "SELECT MAX(updated_at) FROM delegation_tasks WHERE status='in_review'",
     "allow_empty": True},
    {"reader": "Coord boards · /api/coord/summary", "db": "lattice",
     "sql": "SELECT MAX(created_at) FROM coord_event_log"},
    {"reader": "Library writes · /api/memory/activity", "db": "lattice",
     "sql": "SELECT MAX(created_at) FROM nodes"},
    {"reader": "Cognition · reflections", "db": "lattice",
     "sql": "SELECT MAX(created_at) FROM nodes WHERE type='reflection'"},
    {"reader": "Dreams", "db": "lattice",
     "sql": "SELECT MAX(created_at) FROM edges WHERE relationship='dream_association'"},
    {"reader": "X presence · staged posts", "db": "x_staged",
     "sql": "SELECT MAX(proposed_at) FROM staged_posts"},
    {"reader": "Cross-rail active context", "db": "active_context",
     "sql": "SELECT MAX(updated_at) FROM active_context"},
]


def _resolve_dbs() -> dict[str, Path]:
    env = load_env_config()
    root = env.data_root
    return {
        "lattice": env.lattice_db,
        "conversations": env.conversations_db,
        "delegation": root / "delegation.db",
        "x_staged": root / "x_staged.db",
        "active_context": root / "active_context.db",
    }


def last_activity(db_path: Path, sql: str) -> tuple[str | None, str | None]:
    """(timestamp, error). A missing table is a finding, not a crash."""
    if not db_path.is_file():
        return None, "database missing"
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
            row = con.execute(sql).fetchone()
        return (row[0] if row else None), None
    except sqlite3.Error as exc:
        return None, str(exc)


def age_days(ts: str, now: datetime) -> float | None:
    try:
        then = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError):
        return None
    if then.tzinfo is None:
        then = then.astimezone()
    if now.tzinfo is None:
        now = now.astimezone()
    return (now - then).total_seconds() / 86400


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-age", type=float, default=30.0,
                    help="days of silence before a channel is flagged")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    dbs = _resolve_dbs()
    now = datetime.now()
    results = []
    for ch in CHANNELS:
        path = dbs.get(ch["db"])
        ts, err = (None, f"unknown db key {ch['db']!r}") if path is None \
            else last_activity(path, ch["sql"])
        days = age_days(ts, now) if ts else None
        results.append({
            "reader": ch["reader"], "db": ch["db"],
            "last_activity": ts, "age_days": round(days, 1) if days is not None else None,
            "error": err,
            "stale": bool(err) or (
                days is None and not ch.get("allow_empty")
            ) or (days is not None and days > args.max_age),
        })

    if args.json:
        print(json.dumps({"checked_at": now.isoformat(timespec="seconds"),
                          "max_age_days": args.max_age, "channels": results}, indent=2))
        return 1 if any(r["stale"] for r in results) else 0

    print(f"  channels checked: {len(results)}   flagging anything dry > {args.max_age:g}d\n")
    for r in sorted(results, key=lambda x: (x["age_days"] is None, -(x["age_days"] or 0))):
        if r["error"]:
            mark, detail = "ERR ", r["error"][:44]
        elif r["age_days"] is None:
            mark = "    " if not r["stale"] else "NONE"
            detail = "empty — expected for this channel" if not r["stale"] else "no rows at all"
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
