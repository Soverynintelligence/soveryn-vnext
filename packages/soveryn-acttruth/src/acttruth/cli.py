"""CLI: acttruth / python -m acttruth — status|record|recall|stats|proof"""

from __future__ import annotations

import argparse
import json
import sys

from acttruth.audit import get_acttruth, reset_acttruth_cache
from acttruth.paths import default_acttruth_dir, set_default_root


def cmd_status(args: argparse.Namespace) -> int:
    if args.root:
        reset_acttruth_cache()
    if args.crew or args.agent is None:
        from acttruth.unprompted import crew_status

        snap = crew_status(limit=args.limit)
        print(f"acttruth root: {snap['root']}")
        for agent, block in snap["agents"].items():
            b = block["budget"]
            flag = "ALLOWED" if b["allowed"] else "EXHAUSTED"
            print(
                f"\n== {agent} == budget {b['used']}/{b['limit']} "
                f"({b['remaining']} left) — {flag}"
            )
            events = block["recent"]
            if args.failures:
                events = [e for e in events if not e.get("ok", True)]
            for ev in events:
                mark = "ok" if ev.get("ok") else "FAIL"
                tool = f" {ev['tool']}" if ev.get("tool") else ""
                print(f"  [{mark}] {ev['ts']} {ev['kind']}{tool}: {ev['summary']}")
        return 0

    c = get_acttruth(args.root)
    agent = args.agent
    decision = c.budget.check(agent)
    events = c.ledger.recent(agent, limit=args.limit, failures_only=args.failures)
    print(f"acttruth root: {c.root}")
    print(
        f"budget {agent}: {decision.used}/{decision.limit} used, "
        f"{decision.remaining} remaining — "
        f"{'ALLOWED' if decision.allowed else 'EXHAUSTED'}"
    )
    if not decision.allowed:
        print(f"  reason: {decision.reason}")
    print(f"recent events ({len(events)}):")
    for ev in events:
        mark = "ok" if ev.ok else "FAIL"
        tool = f" {ev.tool}" if ev.tool else ""
        print(f"  [{mark}] {ev.ts} {ev.kind}{tool}: {ev.summary}")
    return 0


def cmd_recall(args: argparse.Namespace) -> int:
    c = get_acttruth(args.root)
    brief = c.ledger.recall_brief(args.agent, limit=args.limit)
    print(brief or "(no acttruth events)")
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    c = get_acttruth(args.root)
    ev = c.ledger.record(
        agent_id=args.agent,
        kind=args.kind,
        summary=args.summary,
        ok=not args.fail,
        tool=args.tool,
        tags=args.tag or (),
    )
    print(json.dumps(ev.to_dict(), indent=2))
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    from acttruth.proof import collect_proof

    if args.root:
        reset_acttruth_cache()
    proof = collect_proof(
        window_hours=args.hours,
        include_pytest=args.pytest,
    )
    print(json.dumps(proof.to_dict(), indent=2))
    return 0


def cmd_proof(args: argparse.Namespace) -> int:
    """Shareable receipt — lean into posting proof, not vibes."""
    from acttruth.proof import collect_proof, format_proof_post

    if args.root:
        reset_acttruth_cache()
    proof = collect_proof(
        window_hours=args.hours,
        include_pytest=not args.skip_pytest,
    )
    print(format_proof_post(proof, style=args.style))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="acttruth",
        description="ActTruth by SOVERYN — episodic truth + competence budget",
    )
    p.add_argument(
        "--root",
        default=None,
        help=f"acttruth data dir (default: {default_acttruth_dir()})",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status", help="budget + recent ledger (crew by default)")
    s.add_argument(
        "--agent",
        default=None,
        help="single agent; omit (or pass --crew) for whole ACTIVE_AGENTS crew",
    )
    s.add_argument(
        "--crew",
        action="store_true",
        help="show aetheria + vett + scotty (default when --agent omitted)",
    )
    s.add_argument("--limit", type=int, default=5)
    s.add_argument("--failures", action="store_true")
    s.set_defaults(func=cmd_status)

    r = sub.add_parser("recall", help="print continuity brief block")
    r.add_argument("--agent", default="aetheria")
    r.add_argument("--limit", type=int, default=8)
    r.set_defaults(func=cmd_recall)

    rec = sub.add_parser("record", help="append a manual ledger event")
    rec.add_argument("--agent", default="aetheria")
    rec.add_argument("--kind", default="note")
    rec.add_argument("--summary", required=True)
    rec.add_argument("--tool", default=None)
    rec.add_argument("--fail", action="store_true")
    rec.add_argument("--tag", action="append", default=[])
    rec.set_defaults(func=cmd_record)

    st = sub.add_parser("stats", help="honest JSON stats from the ledger")
    st.add_argument("--hours", type=float, default=24.0)
    st.add_argument(
        "--pytest",
        action="store_true",
        help="also run tests/test_acttruth.py and include pass count",
    )
    st.set_defaults(func=cmd_stats)

    pr = sub.add_parser(
        "proof",
        help="shareable proof receipt (X/markdown) — ledger numbers only",
    )
    pr.add_argument("--hours", type=float, default=24.0)
    pr.add_argument(
        "--style",
        choices=("x", "markdown"),
        default="x",
        help="x = short post; markdown = longer receipt",
    )
    pr.add_argument(
        "--skip-pytest",
        action="store_true",
        help="don't run the proof suite (faster; stats only)",
    )
    pr.set_defaults(func=cmd_proof)

    args = p.parse_args(argv)
    if args.root:
        set_default_root(args.root)
        reset_acttruth_cache()
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
