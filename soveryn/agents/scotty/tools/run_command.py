"""run_command tool for Scotty — bounded subprocess with executable allowlist.

Deliberately NOT a general shell. Two layers of protection:

  1. **Executable allowlist** — the `executable` arg must match one of
     the entries in ALLOWED_EXECUTABLES exactly. python/pytest/ruff/
     black/mypy go to a known python binary inside the soveryn env. git
     gets a per-subcommand allowlist (READ_ONLY_GIT_SUBCOMMANDS) so
     Scotty can run `git log`/`git show`/`git blame`/`git diff` but
     NOT `git push`/`git reset`/`git clean`/`git checkout -- <file>`.

  2. **No shell** — subprocess.run with a list, shell=False (the
     default). No shell metacharacters get interpreted. Even if Scotty
     emits "; rm -rf /" as an arg, it becomes a literal positional
     argument to the executable, not a separate command.

  3. **Clean env** — a minimal PATH so the resolved binaries can find
     coreutils; no inherited env from the calling shell that could
     contain LD_PRELOAD-style overrides.

Output is captured + capped. Timeout enforced. cwd is
SCOTTY_PROJECT_ROOT (no escape via relative cwd).
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from soveryn.agents.scotty.tools.paths import SCOTTY_PROJECT_ROOT
from soveryn.platform.delegation.sandbox import (
    SANDBOX_HOME,
    SandboxUnavailable,
    sandbox_argv,
)
from soveryn.platform.tools.registry import ToolArgError, ToolSpec


# Bounds.
RUN_COMMAND_DEFAULT_TIMEOUT = 60      # seconds
RUN_COMMAND_MAX_TIMEOUT = 300         # seconds — hard ceiling
RUN_COMMAND_OUTPUT_MAX_BYTES = 16 * 1024   # 16 KB per stream (stdout + stderr each)
RUN_COMMAND_MAX_ARGS = 32

PYTHON_BIN = sys.executable
_PY_BIN_DIR = Path(sys.executable).parent

# Executable allowlist. The map key is what Scotty passes as `executable`;
# the value is the resolved absolute path used on the actual subprocess
# call. New tools added here are NEW capabilities — review carefully.
ALLOWED_EXECUTABLES: dict[str, str] = {
    "python": PYTHON_BIN,
    "pytest": str(_PY_BIN_DIR / "pytest"),
    "ruff":   str(_PY_BIN_DIR / "ruff"),
    "black":  str(_PY_BIN_DIR / "black"),
    "mypy":   str(_PY_BIN_DIR / "mypy"),
    "git":    "/usr/bin/git",
}

# Read-only git subcommands. Scotty can ask the git history questions but
# can't push to remotes, reset history, discard tracked changes via clean,
# or check-out away from main. git_restore_file is the supported rollback
# primitive; we don't expose `git checkout` here.
READ_ONLY_GIT_SUBCOMMANDS: frozenset[str] = frozenset({
    "log", "show", "blame", "diff", "ls-files", "rev-parse",
    "branch", "tag", "describe", "remote", "config",
    "shortlog", "for-each-ref", "cat-file",
})

# For python, `-c` lets the model smuggle arbitrary code as an arg —
# the allowlist becomes meaningless. Refuse it; `-m module args...` is fine.
FORBIDDEN_PYTHON_FIRST_ARGS: frozenset[str] = frozenset({"-c", "--command"})


def build_run_command_tool(
    *, owner_agent: str, root: Path = SCOTTY_PROJECT_ROOT, sandbox: bool = False
) -> ToolSpec:
    """Bounded subprocess wrapping ALLOWED_EXECUTABLES with structured I/O.

    ``root`` is the subprocess cwd AND the PYTHONPATH anchor — so a ``python -m``
    / ``pytest`` invocation imports the code under ``root`` (the setuptools
    editable finder is appended to sys.meta_path, so a front-of-path PYTHONPATH
    shadows the live install; verified empirically). Defaults to the live repo;
    delegated execution passes the task worktree.

    ``sandbox=True`` wraps every subprocess in a bubblewrap jail scoped to
    ``root`` (no network; read-only host filesystem except ``root``; ephemeral
    tmpfs ``HOME``). This is set ONLY for delegated execution — normal Scotty use
    (root=SCOTTY_PROJECT_ROOT) runs unsandboxed. Fails CLOSED: if bwrap is
    unavailable the command is refused, never run unsandboxed.
    """
    root = Path(root)

    def handler(args: Mapping[str, Any]) -> Any:
        executable = args.get("executable", "")
        if not isinstance(executable, str) or not executable.strip():
            raise ToolArgError("executable must be a non-empty string")
        if executable not in ALLOWED_EXECUTABLES:
            raise ToolArgError(
                f"executable {executable!r} not in allow-list. "
                f"Allowed: {sorted(ALLOWED_EXECUTABLES.keys())}. "
                f"Open a Friction node if you need a new one."
            )
        resolved_executable = ALLOWED_EXECUTABLES[executable]

        argv = args.get("args", [])
        if not isinstance(argv, list):
            raise ToolArgError("args must be a list of strings (no shell parsing)")
        if len(argv) > RUN_COMMAND_MAX_ARGS:
            raise ToolArgError(
                f"too many args ({len(argv)} > {RUN_COMMAND_MAX_ARGS})"
            )
        for i, a in enumerate(argv):
            if not isinstance(a, str):
                raise ToolArgError(
                    f"args[{i}] must be a string (got {type(a).__name__})"
                )

        # Per-executable secondary guards.
        if executable == "git":
            if not argv or argv[0] not in READ_ONLY_GIT_SUBCOMMANDS:
                raise ToolArgError(
                    f"git subcommand {argv[0] if argv else '<missing>'!r} not allowed via "
                    f"run_command. Read-only subcommands only: "
                    f"{sorted(READ_ONLY_GIT_SUBCOMMANDS)}. "
                    f"Use git_status / git_diff / git_restore_file for the "
                    f"supported write-side primitives."
                )
            # `git config` without a read flag WRITES config — constrain it to
            # the read forms so this stays a read-only surface as advertised.
            if argv[0] == "config":
                read_flags = {"--get", "--get-all", "--get-regexp", "--list", "-l"}
                if not any(a in read_flags for a in argv[1:]):
                    raise ToolArgError(
                        "git config via run_command is read-only: pass one of "
                        "--get / --get-all / --get-regexp / --list. Writing config "
                        "is not permitted."
                    )
        if executable == "python":
            if argv and argv[0] in FORBIDDEN_PYTHON_FIRST_ARGS:
                raise ToolArgError(
                    f"python {argv[0]!r} is not allowed — it lets arbitrary "
                    f"code into the args. Use `-m module` instead."
                )

        timeout = args.get("timeout", RUN_COMMAND_DEFAULT_TIMEOUT)
        if not isinstance(timeout, int) or isinstance(timeout, bool):
            raise ToolArgError("timeout must be an integer (seconds)")
        if timeout <= 0 or timeout > RUN_COMMAND_MAX_TIMEOUT:
            raise ToolArgError(
                f"timeout must be between 1 and {RUN_COMMAND_MAX_TIMEOUT} (got {timeout})"
            )

        # Clean env — only the minimum needed for the resolved binaries to find
        # coreutils and run python imports correctly. Inheriting $PATH from the
        # service environment could pick up LD_PRELOAD-style overrides.
        clean_env = {
            "PATH": f"{_PY_BIN_DIR}:/usr/local/bin:/usr/bin:/bin",
            # Sandboxed runs get the ephemeral tmpfs HOME (caches/dotfiles vanish);
            # unsandboxed normal Scotty use keeps the real HOME.
            "HOME": SANDBOX_HOME if sandbox else str(Path.home()),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
            # Import isolation: code under root shadows the editable-installed
            # live tree (finder is appended to meta_path, so PYTHONPATH wins).
            "PYTHONPATH": str(root),
        }

        cmd = [resolved_executable, *argv]
        if sandbox:
            # Delegated execution: jail the subprocess. Fail CLOSED — if bwrap is
            # unavailable, refuse rather than run Scotty's code unsandboxed.
            try:
                cmd = sandbox_argv(str(root), cmd)
            except SandboxUnavailable as exc:
                return {
                    "executable": executable,
                    "args": list(argv),
                    "returncode": None,
                    "timed_out": False,
                    "stdout_tail": "",
                    "stderr_tail": str(exc),
                    "truncated": False,
                    "message": "refused: delegated command could not be sandboxed",
                }

        try:
            result = subprocess.run(
                cmd,
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=clean_env,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            return {
                "executable": executable,
                "args": list(argv),
                "returncode": None,
                "timed_out": True,
                "stdout_tail": "",
                "stderr_tail": "",
                "truncated": False,
                "message": f"command exceeded {timeout}s timeout and was killed",
            }

        stdout = result.stdout or ""
        stderr = result.stderr or ""
        truncated = False
        if len(stdout.encode("utf-8")) > RUN_COMMAND_OUTPUT_MAX_BYTES:
            stdout = "...[stdout truncated]...\n" + stdout.encode("utf-8")[
                -RUN_COMMAND_OUTPUT_MAX_BYTES:
            ].decode("utf-8", errors="replace")
            truncated = True
        if len(stderr.encode("utf-8")) > RUN_COMMAND_OUTPUT_MAX_BYTES:
            stderr = "...[stderr truncated]...\n" + stderr.encode("utf-8")[
                -RUN_COMMAND_OUTPUT_MAX_BYTES:
            ].decode("utf-8", errors="replace")
            truncated = True

        return {
            "executable": executable,
            "args": list(argv),
            "returncode": result.returncode,
            "timed_out": False,
            "stdout_tail": stdout,
            "stderr_tail": stderr,
            "truncated": truncated,
        }

    return ToolSpec(
        name="run_command",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "executable": {
                    "type": "string",
                    "description": (
                        "Which tool to run. One of: "
                        + ", ".join(sorted(ALLOWED_EXECUTABLES.keys()))
                        + ". For new executables, open a Friction node."
                    ),
                    "enum": sorted(ALLOWED_EXECUTABLES.keys()),
                },
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Arguments as a list of strings (no shell parsing). "
                        f"Up to {RUN_COMMAND_MAX_ARGS} args."
                    ),
                    "maxItems": RUN_COMMAND_MAX_ARGS,
                },
                "timeout": {
                    "type": "integer",
                    "description": (
                        f"Hard timeout in seconds (default "
                        f"{RUN_COMMAND_DEFAULT_TIMEOUT}, max "
                        f"{RUN_COMMAND_MAX_TIMEOUT})."
                    ),
                    "minimum": 1,
                    "maximum": RUN_COMMAND_MAX_TIMEOUT,
                    "default": RUN_COMMAND_DEFAULT_TIMEOUT,
                },
            },
            "required": ["executable", "args"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            f"Run one of the allow-listed executables inside the vnext repo. "
            f"NOT a general shell — args is a list, no metacharacters get "
            f"interpreted. Returns returncode, stdout_tail, stderr_tail "
            f"(each capped at {RUN_COMMAND_OUTPUT_MAX_BYTES // 1024} KB). "
            f"git subcommands restricted to read-only set; use git_restore_file "
            f"for rollback."
        ),
    )
