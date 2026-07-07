"""Git observation tools for Scotty: git_status + git_diff + git_restore_file.

git_status + git_diff are read-only.

git_restore_file is the supported rollback primitive for Scotty's
edit_file: it discards unstaged changes to a single tracked file by
running `git restore <path>`. Hard guards: file must be tracked, file
must not have staged changes, and the path resolves under
SCOTTY_PROJECT_ROOT. Staged changes are refused because they represent
in-progress work Scotty (or anyone else) deliberately committed to —
losing them silently would be a destructive surprise.

All three shell out via subprocess with arg lists (no shell=True, no
string interpolation).
"""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from soveryn.agents.scotty.tools.paths import (
    SCOTTY_PROJECT_ROOT,
    PathOutOfBoundsError,
    resolve_within_root,
)
from soveryn.platform.tools.registry import ToolArgError, ToolSpec


GIT_TIMEOUT_SECONDS = 30
GIT_DIFF_MAX_LINES = 800
GIT_DIFF_MAX_BYTES = 80 * 1024


def _run_git(root: Path, *args: str) -> tuple[int, str, str]:
    """Run a git command with cwd=root, capturing stdout/stderr/returncode.
    Raises on timeout so the tool handler can convert it to a ToolArgError."""
    result = subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
    )
    return result.returncode, result.stdout, result.stderr


def build_git_status_tool(*, owner_agent: str, root: Path = SCOTTY_PROJECT_ROOT) -> ToolSpec:
    """Porcelain-format git status of the repo at ``root`` (default: live repo;
    delegated execution passes the task worktree)."""
    root = Path(root)

    def handler(args: Mapping[str, Any]) -> Any:
        try:
            rc, out, err = _run_git(root, "status", "--porcelain=v1", "--branch")
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
            "cwd": str(root),
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


def build_git_diff_tool(*, owner_agent: str, root: Path = SCOTTY_PROJECT_ROOT) -> ToolSpec:
    """Capped diff of unstaged or staged changes in the repo at ``root``."""
    root = Path(root)

    def handler(args: Mapping[str, Any]) -> Any:
        staged = bool(args.get("staged", False))
        git_args = ["diff", "--no-color"]
        if staged:
            git_args.append("--cached")
        try:
            rc, out, err = _run_git(root, *git_args)
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


def build_git_restore_file_tool(*, owner_agent: str, root: Path = SCOTTY_PROJECT_ROOT) -> ToolSpec:
    """Discard unstaged changes to a single tracked file (rollback for edit_file).

    Behavior: runs `git restore <path>`, which resets the working-tree copy of
    the file to its staged version (or to HEAD if nothing is staged).

    Refused if the file has staged changes — those are deliberate commits-
    in-progress and shouldn't disappear silently. Refused if the file is not
    tracked by git. Path must resolve under SCOTTY_PROJECT_ROOT.
    """

    root = Path(root)

    def handler(args: Mapping[str, Any]) -> Any:
        path_arg = args.get("path", "")
        if not isinstance(path_arg, str) or not path_arg.strip():
            raise ToolArgError("path must be a non-empty string")
        try:
            resolved = resolve_within_root(path_arg, root=root, must_exist=True)
        except PathOutOfBoundsError as e:
            raise ToolArgError(str(e))
        except FileNotFoundError as e:
            raise ToolArgError(str(e))
        if not resolved.is_file():
            raise ToolArgError(f"path {path_arg!r} is not a regular file")
        rel_path = str(resolved.relative_to(root))

        # Verify the file is tracked. `git ls-files --error-unmatch <path>`
        # exits nonzero if the path isn't tracked.
        try:
            rc, _, err = _run_git(root, "ls-files", "--error-unmatch", rel_path)
        except subprocess.TimeoutExpired:
            raise ToolArgError(f"git ls-files timed out after {GIT_TIMEOUT_SECONDS}s")
        if rc != 0:
            raise ToolArgError(
                f"refusing to restore {rel_path!r}: not a tracked file "
                f"(git ls-files: {err.strip()[:200]})"
            )

        # Refuse if there are staged changes for this path. `git diff --cached
        # --name-only -- <path>` outputs the path iff it has staged changes.
        try:
            rc, out, err = _run_git(root, "diff", "--cached", "--name-only", "--", rel_path)
        except subprocess.TimeoutExpired:
            raise ToolArgError(f"git diff timed out after {GIT_TIMEOUT_SECONDS}s")
        if rc != 0:
            raise ToolArgError(f"git diff --cached failed (rc={rc}): {err.strip()[:200]}")
        if out.strip():
            raise ToolArgError(
                f"refusing to restore {rel_path!r}: file has staged changes. "
                f"Unstage with `git reset HEAD <path>` (Jon's call, not Scotty's), "
                f"or commit them first, then restore."
            )

        # Do the actual restore.
        try:
            rc, out, err = _run_git(root, "restore", "--", rel_path)
        except subprocess.TimeoutExpired:
            raise ToolArgError(f"git restore timed out after {GIT_TIMEOUT_SECONDS}s")
        if rc != 0:
            raise ToolArgError(f"git restore failed (rc={rc}): {err.strip()[:500]}")

        return {
            "path": str(resolved),
            "restored": True,
            "message": f"unstaged changes to {rel_path} discarded; file matches index",
        }

    return ToolSpec(
        name="git_restore_file",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Path to restore, relative to the vnext repo root or "
                        "absolute. Must be tracked by git and must NOT have "
                        "staged changes."
                    ),
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Discard unstaged changes to a single tracked file by running "
            "`git restore <path>`. The rollback primitive for edit_file: use "
            "after a bad edit to revert the working-tree copy to what's in "
            "the index (or HEAD if nothing's staged). Refused if the file has "
            "staged changes (those are deliberate; shouldn't disappear)."
        ),
    )
