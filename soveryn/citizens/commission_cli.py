"""CLI for the commissions queue.

  python -m soveryn.citizens.commission_cli enqueue aetheria "summarize X into outbox"
  python -m soveryn.citizens.commission_cli list aetheria
  python -m soveryn.citizens.commission_cli show <id>
  python -m soveryn.citizens.commission_cli cancel <id>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from soveryn.citizens import commissions
from soveryn.citizens.registry import connect

DEFAULT_DB = Path(
    os.environ.get(
        "SOVERYN_CITIZENS_DB",
        str(Path.home() / "soveryn_vnext" / "data" / "citizens.db"),
    )
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="soveryn.citizens.commission_cli")
    parser.add_argument(
        "--db", type=Path, default=DEFAULT_DB, help="path to citizens.db"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_enq = sub.add_parser("enqueue", help="put work on a citizen's desk")
    p_enq.add_argument("citizen_id")
    p_enq.add_argument("body", help="what is being asked")
    p_enq.add_argument("--title", default="")

    p_list = sub.add_parser("list", help="list commissions for a citizen")
    p_list.add_argument("citizen_id")
    p_list.add_argument("--state", default=None)
    p_list.add_argument("--limit", type=int, default=20)

    p_show = sub.add_parser("show", help="show one commission")
    p_show.add_argument("commission_id")

    p_cancel = sub.add_parser("cancel", help="cancel a queued commission")
    p_cancel.add_argument("commission_id")
    p_cancel.add_argument("--reason", default="cancelled via CLI")

    args = parser.parse_args(argv)
    db = args.db
    if not db.exists():
        print(f"no registry at {db} — run: python -m soveryn.citizens.census",
              file=sys.stderr)
        return 2

    with connect(db) as conn:
        if args.cmd == "enqueue":
            text = args.body.strip()
            if args.title.strip():
                text = f"{args.title.strip()}\n\n{text}"
            cid = commissions.enqueue(
                conn, args.citizen_id, text, at=_utc_now()
            )
            row = commissions.get(conn, cid)
            print(json.dumps(row, indent=2))
            return 0
        if args.cmd == "list":
            rows = commissions.for_citizen(
                conn, args.citizen_id, limit=args.limit, state=args.state
            )
            print(json.dumps(rows, indent=2))
            return 0
        if args.cmd == "show":
            row = commissions.get(conn, args.commission_id)
            if row is None:
                print(f"not found: {args.commission_id}", file=sys.stderr)
                return 1
            print(json.dumps(row, indent=2))
            return 0
        if args.cmd == "cancel":
            try:
                row = commissions.cancel(
                    conn, args.commission_id, at=_utc_now(), reason=args.reason
                )
            except KeyError:
                print(f"not found: {args.commission_id}", file=sys.stderr)
                return 1
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            print(json.dumps(row, indent=2))
            return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
