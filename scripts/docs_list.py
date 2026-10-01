#!/usr/bin/env python3
"""docs-list: doc routing report for the house.

Adopted from steipete/agent-scripts docs-list.ts (2026-09-29), adapted to
the house format. Every ROUTING doc (one an agent might need to find and
act on) should carry two header lines near the top:

    summary: one line — what this doc is
    read_when: one line — the trigger that means "open this now"

Design docs and history don't need them; runbooks, ops docs, and anything
a citizen must find under time pressure do.

Report-only by default. `--strict <dirs...>` exits 1 if any .md in those
dirs (relative to repo root) lacks the headers — wire into verify when the
seeded set is clean and the convention has spread.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Docs that already carry the headers (seeded 2026-09-29).
ROUTING_DOCS = [
    "docs/runbooks/env-var-map.md",
    "docs/runbooks/secrets-state-backup.md",
    "docs/ops/DEPLOY-vnext.md",
    "docs/ops/README.md",
]

SUMMARY_RE = re.compile(r"^summary:\s*\S", re.M | re.I)
READ_WHEN_RE = re.compile(r"^read_when:\s*\S", re.M | re.I)


def check(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return [f"{path}: unreadable ({e})"]
    missing = []
    head = "\n".join(text.splitlines()[:20])  # header lines must be near the top
    if not SUMMARY_RE.search(head):
        missing.append("summary")
    if not READ_WHEN_RE.search(head):
        missing.append("read_when")
    return [f"{path.relative_to(REPO)}: missing {', '.join(missing)}"] if missing else []


def main() -> int:
    args = sys.argv[1:]
    strict = "--strict" in args
    args = [a for a in args if a != "--strict"]

    targets: list[Path] = []
    if args:
        for d in args:
            p = REPO / d
            if p.is_dir():
                targets.extend(sorted(p.rglob("*.md")))
            elif p.is_file():
                targets.append(p)
            else:
                print(f"no such path: {d}", file=sys.stderr)
                return 1
    else:
        targets = [REPO / rel for rel in ROUTING_DOCS if (REPO / rel).is_file()]
        missing_files = [rel for rel in ROUTING_DOCS if not (REPO / rel).is_file()]
        for rel in missing_files:
            print(f"FAIL {rel}: listed in ROUTING_DOCS but missing")

    problems: list[str] = []
    for p in targets:
        problems.extend(check(p))

    if problems:
        for p in problems:
            print(f"MISSING {p}")
        print(f"\n{len(problems)} doc(s) lack routing headers")
        if strict:
            return 1
        print("(report-only; use --strict to fail)")
        return 0

    print(f"docs ok: {len(targets)} checked")
    return 0


if __name__ == "__main__":
    sys.exit(main())
