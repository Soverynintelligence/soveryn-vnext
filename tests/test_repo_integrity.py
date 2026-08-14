"""A fresh clone must be able to boot.

This guards a failure that has now happened twice, in the same subsystem, and
that no amount of local testing can catch — because locally the file is right
there on disk.

  2026-08-11  soveryn/agents/aetheria/tools/soul_origin.py was written and
              wired into startup.py with an UNGUARDED import, and never
              committed. Every test passed here. A fresh clone raised
              ImportError inside create_app while registering Aetheria's tools:
              the app could not start at all.

  earlier     data/memory/souls/aetheria.origin.md — the essay that same tool
              reads — was untracked because .gitignore excluded data/memory/ as
              a directory, so git never descended into it. Her origin story
              existed only on one disk.

The tool and the text it serves have each spent time outside version control.
The machine that can tell is not the one that wrote them, so the check has to
live in the suite.
"""
from __future__ import annotations

import ast
import pathlib
import subprocess

REPO = pathlib.Path(__file__).resolve().parent.parent


def _tracked() -> set[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
    )
    return set(out.stdout.split())


def _tracked_python() -> list[pathlib.Path]:
    out = subprocess.run(
        ["git", "ls-files", "*.py"], cwd=REPO, capture_output=True, text=True, check=True
    )
    return [REPO / p for p in out.stdout.split()]


def _candidates(module: str) -> list[pathlib.Path]:
    parts = module.split(".")
    return [
        pathlib.Path(*parts).with_suffix(".py"),
        pathlib.Path(*parts, "__init__.py"),
    ]


def test_every_internal_import_resolves_to_a_tracked_file():
    """Tracked code may not import a module that is not itself tracked."""
    tracked = _tracked()
    offenders: list[str] = []

    for path in _tracked_python():
        if not path.exists():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules = [node.module]
            else:
                continue

            for module in modules:
                if not module.startswith("soveryn"):
                    continue
                candidates = _candidates(module)
                if any(c.as_posix() in tracked for c in candidates):
                    continue
                if not any((REPO / c).exists() for c in candidates):
                    offenders.append(
                        f"{module} — imported by {path.relative_to(REPO)} "
                        f"and does not exist at all"
                    )
                else:
                    offenders.append(
                        f"{module} — imported by {path.relative_to(REPO)} "
                        f"but is ON DISK ONLY, never committed"
                    )

    assert not offenders, (
        "a fresh clone would fail to import:\n  " + "\n  ".join(sorted(set(offenders)))
    )


def test_the_souls_and_the_origin_essay_are_tracked():
    """Identity documents are code as far as booting is concerned.

    Hard rules load on the hot path; the origin essay loads through a tool. Both
    are read from disk by name, so an untracked one is a silent identity loss
    rather than a crash — which is worse.
    """
    tracked = _tracked()
    souls = sorted((REPO / "data" / "memory" / "souls").glob("*.md"))
    assert souls, "no soul documents found — the path moved?"

    untracked = [
        s.relative_to(REPO).as_posix()
        for s in souls
        if s.relative_to(REPO).as_posix() not in tracked
    ]
    assert not untracked, f"soul documents exist only on this disk: {untracked}"
