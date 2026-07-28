"""SOVERYN vNext — dispatch-time validation and ground truth for delegation.

Two jobs, deliberately kept apart because they have different failure costs:

``acceptance_problem`` REJECTS a task that cannot possibly pass. It is a gate.
``path_facts`` REPORTS which referenced paths exist. It is grounding, not a gate.

Why the split — measured, not assumed
-------------------------------------
Across all 11 dispatches in the project's history (10 failed, 1 passed):

* **5 of 11 acceptance commands never invoked a test runner.** They took the
  form ``python -m tests.test_active_context --run-smoke``: a module executed
  directly. That clears the old prefix gate (``python -m``) while requiring
  ``tests/`` to be an importable package that runs its own suite on import —
  which it is not. Those four failures were sealed before Scotty woke up.

* **Objective LENGTH does not predict failure.** The single task that reached
  ``in_review`` was 947 characters over 17 lines — longer than seven of the ten
  that failed (243–1062). A size cap was the obvious-looking gate and the data
  refutes it; it would have rejected the only success. Not implemented.

What separated the pass was PRECISION, not brevity: exact signature, exact
expected outputs, and explicit instruction to create the files. Precision is not
something a validator can measure. What a validator *can* do is remove the
specific ambiguity that bit hardest — a task naming a path that does not exist
(``soveryn/context/`` as a scope boundary, a test file that was never written).
So instead of guessing whether the prose is precise enough, we hand Scotty the
ground truth about every path the task names and let him act on it.

That is the house pattern: make the fact visible rather than word the warning
more carefully. A prose caveat did not hold in the audit tool either.
"""
from __future__ import annotations

import re
import shlex
from pathlib import Path

# Commands that actually RUN a check and report a real exit code. `unittest` is
# included because `python -m unittest tests.test_x` is a genuine runner; a bare
# `python -m tests.test_x` is not, and that distinction is the whole point.
CHECK_RUNNERS = frozenset({
    "pytest", "unittest", "mypy", "ruff", "flake8", "black", "compileall",
})

_PYTHON = re.compile(r"^python[\d.]*$")

# A path-like token: at least one slash, or a bare *.py filename. Trailing
# punctuation from prose ("touch soveryn/x.py.") is stripped by the caller.
_PATH_TOKEN = re.compile(r"[A-Za-z0-9_.\-/]*[/][A-Za-z0-9_.\-/]*|[A-Za-z0-9_.\-]+\.py")


def acceptance_problem(acceptance: str) -> str | None:
    """Return a human-readable problem with *acceptance*, or None if it can run.

    This is a hard gate at dispatch time. The message is written to be actionable
    by the agent that receives it — it says what to write instead, not merely
    that the input was rejected.
    """
    if not isinstance(acceptance, str) or not acceptance.strip():
        return "acceptance must be a non-empty string"

    try:
        argv = shlex.split(acceptance)
    except ValueError as exc:
        return f"acceptance command has unbalanced quotes and cannot be parsed: {exc}"
    if not argv:
        return "acceptance command is empty"

    head = Path(argv[0]).name

    if head in CHECK_RUNNERS:
        return None

    if _PYTHON.match(head):
        if len(argv) < 3 or argv[1] != "-m":
            return (
                f"acceptance runs {acceptance!r}, which executes a script rather "
                "than a check. Use a test runner: "
                "'python -m pytest tests/test_<name>.py -q'."
            )
        module_root = argv[2].split(".")[0]
        if module_root not in CHECK_RUNNERS:
            return (
                f"acceptance runs the module {argv[2]!r} directly. That only works "
                "if it executes its own suite on import, which test modules in this "
                "repo do not — the command exits 0 without running anything, or "
                "fails on import. Invoke a runner instead: "
                f"'python -m pytest {argv[2].replace('.', '/')}.py -q'."
            )
        return None

    return (
        f"acceptance must start with a check runner ({', '.join(sorted(CHECK_RUNNERS))}) "
        f"or 'python -m <runner>' — got {argv[0]!r}."
    )


def referenced_paths(*texts: str) -> list[str]:
    """Extract repo-relative path-like tokens from task prose, in first-seen order."""
    seen: dict[str, None] = {}
    for text in texts:
        for raw in _PATH_TOKEN.findall(text or ""):
            token = raw.strip(".,;:'\"()[]")
            if not token or token.startswith(("http", "//")):
                continue
            # Bare dotted names (soveryn.platform.x) are modules, not paths.
            if "/" not in token and not token.endswith(".py"):
                continue
            seen.setdefault(token.lstrip("./"), None)
    return list(seen)


def path_facts(paths: list[str], repo_root: str | Path) -> tuple[list[str], list[str]]:
    """Split *paths* into (existing, missing) relative to *repo_root*.

    Purely observational — a missing path is often correct (the task is to create
    it). The value is that Scotty is told WHICH, instead of assuming.
    """
    root = Path(repo_root)
    existing: list[str] = []
    missing: list[str] = []
    for p in paths:
        (existing if (root / p).exists() else missing).append(p)
    return existing, missing


def ground_truth_block(objective: str, scope: str, acceptance: str,
                       repo_root: str | Path) -> str:
    """Render the path ground-truth section for Scotty's directive.

    Empty string when the task names no paths — never emit a header with nothing
    under it, which reads as "checked, found nothing" rather than "not checked".
    """
    existing, missing = path_facts(
        referenced_paths(objective, scope, acceptance), repo_root
    )
    if not existing and not missing:
        return ""

    lines = ["GROUND TRUTH — paths this task names, checked against the worktree:"]
    for p in existing:
        lines.append(f"    EXISTS       {p}")
    for p in missing:
        lines.append(f"    DOES NOT EXIST  {p}")
    if missing:
        lines.append(
            "  A path marked DOES NOT EXIST is not necessarily an error — creating "
            "it may be the task. But do not assume it is there and do not report "
            "success against it without creating it first."
        )
    return "\n".join(lines) + "\n\n"
