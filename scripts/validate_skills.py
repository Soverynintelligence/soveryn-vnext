#!/usr/bin/env python3
"""Validate citizen skills: routing integrity between skill bodies and indexes.

The skills system (soveryn.agents.skills) routes through per-agent
_index.md files: the index is the tiny always-on layer the model sees;
bodies load on demand. That means the load-bearing invariant is
BOTH-DIRECTION index coverage:

  - every skill body must be listed in its agent's _index.md, or the model
    never learns the skill exists (silent capability loss), and
  - every _index.md entry must have a body, or load_skill returns "" and
    the model follows a ghost.

Adopted from steipete/agent-scripts validate-skills (2026-09-29), adapted
to the house format (plain markdown, no YAML front matter).

Usage: python3 scripts/validate_skills.py [--quiet]
Exit 0 clean, 1 problems found. CI/pre-commit friendly.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO / "data" / "memory" / "skills"


def problems_for_agent(agent_dir: Path) -> list[str]:
    problems: list[str] = []
    agent = agent_dir.name
    index_path = agent_dir / "_index.md"
    bodies = sorted(
        p.stem
        for p in agent_dir.glob("*.md")
        if p.name != "_index.md"
    )

    # An agent dir with no skills and no index is legitimate: get_skill_index
    # returns "" for missing _index.md and that is the designed empty state.
    if not index_path.is_file():
        if bodies:
            problems.append(
                f"{agent}: skill bodies exist but _index.md is missing — "
                f"not in _index.md (unrouted): {', '.join(bodies)}"
            )
        return problems

    index_text = index_path.read_text(encoding="utf-8")

    if not index_text.strip():
        problems.append(f"{agent}: _index.md is empty")
        if bodies:
            problems.append(f"{agent}: skill bodies exist but are unrouted: {', '.join(bodies)}")
        return problems

    # bodies → index: every body must be referenced by name in the index
    for body in bodies:
        if body not in index_text:
            problems.append(
                f"{agent}: skill '{body}' exists but is not in _index.md — "
                "the model will never route to it"
            )

    # index → bodies: every referenced skill name must have a body file
    import re

    for ref in re.findall(r"`([a-z0-9_-]+)\.md`|(^|\s)([a-z0-9_-]+)\.md\b", index_text, re.M):
        name = next(g for g in ref if g)
        if not name or name == "_index":
            continue
        if not (agent_dir / f"{name}.md").is_file():
            problems.append(
                f"{agent}: _index.md references '{name}.md' but no body file exists — "
                "load_skill would return empty and the model follows a ghost"
            )

    # bodies: non-empty, titled
    for body in bodies:
        p = agent_dir / f"{body}.md"
        text = p.read_text(encoding="utf-8")
        if not text.strip():
            problems.append(f"{agent}: skill '{body}' is empty")
        elif not text.splitlines()[0].strip():
            problems.append(f"{agent}: skill '{body}' has no title line")

    return problems


def main() -> int:
    quiet = "--quiet" in sys.argv
    if not SKILLS_DIR.is_dir():
        print(f"skills dir not found: {SKILLS_DIR}")
        return 1

    all_problems: list[str] = []
    for agent_dir in sorted(SKILLS_DIR.iterdir()):
        if agent_dir.is_dir():
            all_problems.extend(problems_for_agent(agent_dir))

    if all_problems:
        for p in all_problems:
            print(f"FAIL {p}")
        print(f"\n{len(all_problems)} skill problem(s)")
        return 1
    if not quiet:
        agents = sorted(d.name for d in SKILLS_DIR.iterdir() if d.is_dir())
        print(f"skills ok: {', '.join(agents)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
