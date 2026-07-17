"""run_pytest tool for Scotty.

Runs pytest against the vnext repo with a hard timeout. The target path
must resolve under tests/ (or be omitted to mean "the whole suite").
Output is captured and capped so the model gets parseable summary data
plus the tail of stdout for diagnosis.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from soveryn.agents.scotty.tools.paths import (
    SCOTTY_PROJECT_ROOT,
    PathOutOfBoundsError,
    resolve_within_root,
)
from soveryn.platform.delegation.sandbox import (
    SANDBOX_HOME,
    SandboxUnavailable,
    sandbox_argv,
)
from soveryn.platform.tools.registry import ToolArgError, ToolSpec


PYTEST_TIMEOUT_SECONDS = 180         # 3 minutes — full suite ran in ~8s today
PYTEST_OUTPUT_MAX_BYTES = 16 * 1024  # 16 KB tail of stdout
PYTHON_BIN = sys.executable


def build_run_pytest_tool(
    *, owner_agent: str, root: Path = SCOTTY_PROJECT_ROOT, sandbox: bool = False
) -> ToolSpec:
    """``sandbox=True`` jails pytest in bubblewrap (no network; host read-only
    except ``root``). Set ONLY for delegated execution — normal Scotty use runs
    unsandboxed. Fails CLOSED: if bwrap is unavailable, pytest is refused."""
    root = Path(root).resolve()
    tests_dir = (root / "tests").resolve()

    def handler(args: Mapping[str, Any]) -> Any:
        target_arg = args.get("target", "tests/")
        if not isinstance(target_arg, str):
            raise ToolArgError("target must be a string")
        # pytest supports "path::test_name" selector syntax — split that off
        # before path resolution and re-attach when invoking pytest.
        if "::" in target_arg:
            path_part, _sep, selector = target_arg.partition("::")
        else:
            path_part, selector = target_arg, ""
        try:
            resolved_path = resolve_within_root(path_part, root=root, must_exist=True)
        except PathOutOfBoundsError as e:
            raise ToolArgError(str(e))
        except FileNotFoundError as e:
            raise ToolArgError(str(e))
        # Constrain to tests/ specifically — Scotty doesn't run arbitrary modules.
        try:
            resolved_path.relative_to(tests_dir)
        except ValueError:
            raise ToolArgError(
                f"target {target_arg!r} must be under tests/; resolved to "
                f"{resolved_path} which is outside {tests_dir}"
            )
        # Reassemble target with selector for pytest if one was provided.
        pytest_target = f"{resolved_path}::{selector}" if selector else str(resolved_path)
        # `resolved_target` is the path component, exposed in the result for clarity.
        resolved_target = resolved_path

        # Import isolation: PYTHONPATH=root so pytest imports the code under root
        # (the worktree), shadowing the editable-installed live tree. The finder
        # is appended to sys.meta_path, so a front-of-path PYTHONPATH wins.
        env = dict(os.environ)
        existing_pp = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{root}{os.pathsep}{existing_pp}" if existing_pp else str(root)

        cmd = [PYTHON_BIN, "-m", "pytest", pytest_target, "-q", "--tb=line"]
        if sandbox:
            # Delegated execution: jail pytest (it runs Scotty-written worktree
            # code). Ephemeral tmpfs HOME; fail CLOSED if bwrap is unavailable.
            env["HOME"] = SANDBOX_HOME
            try:
                cmd = sandbox_argv(str(root), cmd)
            except SandboxUnavailable as exc:
                return {
                    "target": str(resolved_target),
                    "returncode": None,
                    "passed": False,
                    "summary_line": "refused: pytest could not be sandboxed",
                    "stdout_tail": "",
                    "stderr_tail": str(exc),
                    "truncated": False,
                }

        try:
            result = subprocess.run(
                cmd,
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=PYTEST_TIMEOUT_SECONDS,
                env=env,
            )
        except subprocess.TimeoutExpired:
            raise ToolArgError(
                f"pytest exceeded the {PYTEST_TIMEOUT_SECONDS}s time cap and was "
                f"killed; target={target_arg!r}"
            )

        stdout = result.stdout or ""
        stderr = result.stderr or ""
        truncated = False
        if len(stdout.encode("utf-8")) > PYTEST_OUTPUT_MAX_BYTES:
            tail = stdout.encode("utf-8")[-PYTEST_OUTPUT_MAX_BYTES:].decode(
                "utf-8", errors="replace"
            )
            stdout = "...[truncated]...\n" + tail
            truncated = True
        # Look for the pytest summary line for parseable result.
        summary_line = ""
        for line in reversed(stdout.splitlines()):
            if "passed" in line or "failed" in line or "error" in line:
                summary_line = line.strip()
                break

        return {
            "target": str(resolved_target),
            "returncode": result.returncode,
            "passed": result.returncode == 0,
            "summary_line": summary_line,
            "stdout_tail": stdout,
            "stderr_tail": stderr[-2048:] if stderr else "",
            "truncated": truncated,
        }

    return ToolSpec(
        name="run_pytest",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": (
                        "Test path under tests/. Examples: 'tests/' for the full "
                        "suite, 'tests/test_coordination_store.py' for one file, "
                        "'tests/test_coordination_store.py::test_create_node_returns_node_with_open_status' "
                        "for one test. Must resolve under tests/; rejected otherwise. "
                        "Defaults to 'tests/' (the full suite)."
                    ),
                },
            },
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            f"Run pytest against a path under tests/. Hard timeout of "
            f"{PYTEST_TIMEOUT_SECONDS}s; output capped at "
            f"{PYTEST_OUTPUT_MAX_BYTES // 1024} KB (tail of stdout retained). "
            f"Returns passed (bool from returncode), summary_line (the pytest "
            f"summary like '943 passed in 6.5s'), and stdout_tail for failure "
            f"diagnosis. Use this to verify changes before reporting Ready."
        ),
    )
