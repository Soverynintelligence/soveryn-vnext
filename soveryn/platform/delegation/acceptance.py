"""SOVERYN vNext — delegation acceptance runner.

Runs a task's acceptance command inside its worktree and reports pass/fail. This
is the gate that decides whether Scotty's work reaches human review: green →
in_review, red → failed. It must run the command AS WRITTEN (shell-style quoting
respected) and import the worktree's code, not the live tree.

Extracted from startup.py so the two load-bearing properties are unit-testable:
  * ``shlex.split`` — a command like ``python -m pytest -k "not slow" tests/``
    keeps ``not slow`` as one argument; naive ``str.split`` would shatter it.
  * ``PYTHONPATH=worktree`` — pytest imports the worktree's soveryn, shadowing
    the editable-installed live tree (finder is appended to sys.meta_path).
"""
from __future__ import annotations

import logging
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

ACCEPTANCE_TIMEOUT_SECONDS = 300


def run_acceptance_in_worktree(
    worktree_path: str,
    acceptance: str,
    *,
    timeout: int = ACCEPTANCE_TIMEOUT_SECONDS,
) -> tuple[bool, str]:
    """Run *acceptance* in *worktree_path*. Returns ``(passed, combined_output)``.

    Never raises — any failure (bad command, timeout, OS error) returns
    ``(False, message)`` so the engine records a clean red rather than crashing.
    """
    try:
        argv = shlex.split(acceptance)
    except ValueError as exc:  # unbalanced quotes, etc.
        return False, f"could not parse acceptance command {acceptance!r}: {exc}"
    if not argv:
        return False, "acceptance command is empty"

    pybin_dir = Path(sys.executable).parent
    # Throwaway HOME so code executed during acceptance (pytest collects and runs
    # the worktree's Python, which Scotty writes) writes caches/dotfiles to a temp
    # dir, not the real user HOME. Reduces the blast radius of the executed code.
    try:
        with tempfile.TemporaryDirectory(prefix="acc_home_") as throwaway_home:
            env = {
                "PATH": f"{pybin_dir}:/usr/local/bin:/usr/bin:/bin",
                "HOME": throwaway_home,
                "LANG": os.environ.get("LANG", "C.UTF-8"),
                "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
                # Import isolation: the worktree's code shadows the live editable install.
                "PYTHONPATH": str(Path(worktree_path)),
            }
            result = subprocess.run(
                argv,
                cwd=worktree_path,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
    except subprocess.TimeoutExpired:
        return False, f"acceptance command exceeded {timeout}s and was killed"
    except Exception as exc:  # noqa: BLE001 — never propagate into the engine
        logger.exception("acceptance runner: unexpected error for %s", worktree_path)
        return False, str(exc)

    return result.returncode == 0, (result.stdout or "") + (result.stderr or "")
