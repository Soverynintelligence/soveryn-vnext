"""Git observation tools for Scotty: git_status + git_diff.

Both shell out via subprocess with arg lists (no shell=True, no string
interpolation). All paths are validated against SCOTTY_PROJECT_ROOT.
"""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from typing import Any

from soveryn.agents.scotty.tools.paths import SCOTTY_PROJECT_ROOT
from soveryn.platform.tools.registry import ToolArgError, ToolSpec


GIT_TIMEOUT_SECONDS = 30
GIT_DIFF_MAX_LINES = 800
GIT_DIFF_MAX_BYTES = 80 * 1024


def _run_git(*args: str) -> tuple[int, str, str]:
    """Run a git command, capture stdout/stderr/returncode. Raises on timeout
    so the tool handler can convert it to a ToolArgError."""
    result = subprocess.run(
        ["git", *args],
        cwd=str(SCOTTY_PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
    )
    return result.returncode, result.stdout, result.stderr


def build_git_status_tool(*, owner_agent: str) -> ToolSpec:
    """Porcelain-format git status of the vnext repo."""

    def handler(args: Mapping[str, Any]) -> Any:
        try:
            rc, out, err = _run_git("status", "--porcelain=v1", "--branch")
        except subprocess.TimeoutExpired:
            raise ToolArgError(f"git status timed out after {GIT_TIMEOUT_SECONDS}s")
        if rc != 0:
            raise ToolArgError(f"git status failed (rc={rc}): {err.strip()[:500]}")
        lines = out.splitlines()
        branch_line = next((l for l in lines if l.startswith("##")), None)
        change_lines = [l for l in lines if not l.startswith("##")]
        return {
            "branch_summary": (branch_line or "").lstrip("# ").strip(),
            "changes": change_lines,
            "change_count": len(change_lines),
            "clean": len(change_lines) == 0,
            "cwd": str(SCOTTY_PROJECT_ROOT),
        }

    return ToolSpec(
        name="git_status",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Run `git status --porcelain=v1 --branch` against the vnext "
            "repository. Returns parsed branch summary, list of change lines, "
            "change count, and whether the working tree is clean."
        ),
    )


def build_git_diff_tool(*, owner_agent: str) -> ToolSpec:
    """Capped diff of unstaged or staged changes."""

    def handler(args: Mapping[str, Any]) -> Any:
        staged = bool(args.get("staged", False))
        git_args = ["diff", "--no-color"]
        if staged:
            git_args.append("--cached")
        try:
            rc, out, err = _run_git(*git_args)
        except subprocess.TimeoutExpired:
            raise ToolArgError(f"git diff timed out after {GIT_TIMEOUT_SECONDS}s")
        if rc != 0:
            raise ToolArgError(f"git diff failed (rc={rc}): {err.strip()[:500]}")
        lines = out.splitlines()
        truncated_lines = len(lines) > GIT_DIFF_MAX_LINES
        if truncated_lines:
            lines = lines[:GIT_DIFF_MAX_LINES]
        diff_text = "\n".join(lines)
        truncated_bytes = False
        if len(diff_text.encode("utf-8")) > GIT_DIFF_MAX_BYTES:
            # Cut at the byte cap; mark truncated.
            diff_text = diff_text.encode("utf-8")[:GIT_DIFF_MAX_BYTES].decode(
                "utf-8", errors="replace"
            )
            truncated_bytes = True
        return {
            "staged": staged,
            "diff": diff_text,
            "line_count": len(lines),
            "truncated_lines": truncated_lines,
            "truncated_bytes": truncated_bytes,
            "max_lines": GIT_DIFF_MAX_LINES,
            "max_bytes": GIT_DIFF_MAX_BYTES,
        }

    return ToolSpec(
        name="git_diff",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "staged": {
                    "type": "boolean",
                    "description": (
                        "If true, run `git diff --cached` (staged changes). "
                        "If false or omitted, run `git diff` (unstaged)."
                    ),
                },
            },
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            f"Run `git diff` (or `git diff --cached` if staged=true) against the "
            f"vnext repo. Output capped at {GIT_DIFF_MAX_LINES} lines and "
            f"{GIT_DIFF_MAX_BYTES // 1024} KB; sets truncated_lines/truncated_bytes "
            f"so you know when you're looking at a partial view."
        ),
    )
