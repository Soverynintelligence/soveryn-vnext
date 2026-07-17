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
from pathlib import Path

from soveryn.platform.delegation.sandbox import BWRAP, SANDBOX_HOME, sandbox_argv

logger = logging.getLogger(__name__)

ACCEPTANCE_TIMEOUT_SECONDS = 300


def run_acceptance_in_worktree(
    worktree_path: str,
    acceptance: str,
    *,
    timeout: int = ACCEPTANCE_TIMEOUT_SECONDS,
) -> tuple[bool, str]:
    """Run *acceptance* in *worktree_path*, SANDBOXED. Returns ``(passed, output)``.

    The command runs inside bubblewrap (see ``_sandbox_argv``): no network, and
    the filesystem is read-only except the worktree and an ephemeral tmpfs /tmp.
    Fails CLOSED — if bwrap is unavailable it refuses rather than run
    Scotty-written code unsandboxed on the host. Never raises: any failure
    returns ``(False, message)`` so the engine records a clean red.
    """
    if BWRAP is None:
        return False, ("acceptance sandbox unavailable: bwrap (bubblewrap) not "
                       "found on PATH. Refusing to run acceptance unsandboxed.")
    try:
        argv = shlex.split(acceptance)
    except ValueError as exc:  # unbalanced quotes, etc.
        return False, f"could not parse acceptance command {acceptance!r}: {exc}"
    if not argv:
        return False, "acceptance command is empty"

    pybin_dir = Path(sys.executable).parent
    env = {
        "PATH": f"{pybin_dir}:/usr/local/bin:/usr/bin:/bin",
        "HOME": SANDBOX_HOME,  # ephemeral tmpfs inside the sandbox — caches/dotfiles vanish
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        # Import isolation: the worktree's code shadows the live editable install.
        "PYTHONPATH": str(Path(worktree_path)),
    }
    try:
        result = subprocess.run(
            sandbox_argv(worktree_path, argv),
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
