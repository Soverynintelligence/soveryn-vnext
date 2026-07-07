"""Vett's read-only git-awareness tools.

Vett can read a file's *content*; these let her also see *where it lives* in the
repository — current branch, clean/dirty, which files are staged/modified/
untracked, recent history, and the working diff. This closes a real verification
gap: she could confirm what a file says but miss that it's uncommitted, modified,
or sitting on a feature branch.

Read-only by construction. Each tool runs one allow-listed git subcommand
(status / log / diff / rev-parse) via ``subprocess.run(["git", ...])`` — no
shell, no user-supplied flags interpolated into the argv, and no mutating
subcommand (add/commit/checkout/reset) anywhere in this module. There is no path
by which these tools change a repo. The ``test_tools_never_mutate_repo`` test
pins that guarantee.

A ``path`` argument (a file or directory) selects the repo — its containing git
toplevel is resolved. When ``path`` is omitted the tool falls back to the
configured default repo root (the vNext repo). A path outside any git repo
returns ``{"error": "not_a_repo"}`` rather than raising.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Mapping

from soveryn.platform.tools.registry import ToolSpec

_TIMEOUT = 10  # seconds — git status/log/diff are fast; a hang is a bug, not work
_DEFAULT_LOG_COUNT = 10
_MAX_LOG_COUNT = 100
_DEFAULT_DIFF_LINES = 200
_FS = "\x1f"  # unit separator — safe field delimiter for --pretty (never in subjects)


def _default_repo_root() -> Path:
    import os
    return Path(os.path.expanduser("~/soveryn_vnext"))


def _resolve_repo(path_arg: Any, default_root: Path) -> tuple[Path | None, dict | None]:
    """Resolve the git toplevel for *path_arg* (file or dir), else *default_root*.

    Returns ``(repo_root, None)`` on success, or ``(None, error_dict)`` on
    failure so callers can early-return the honest error shape.
    """
    if isinstance(path_arg, str) and path_arg.strip():
        target = Path(path_arg).expanduser()
        if not target.exists():
            return None, {"error": "not_found", "message": f"No such path: {target}"}
        start = target if target.is_dir() else target.parent
    else:
        start = default_root
        if not start.exists():
            return None, {"error": "not_found", "message": f"No such path: {start}"}

    try:
        result = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return None, {"error": "timeout", "message": "git rev-parse timed out"}
    if result.returncode != 0:
        return None, {"error": "not_a_repo",
                      "message": f"{start} is not inside a git repository."}
    return Path(result.stdout.strip()), None


def _run_git(repo: Path, *args: str) -> tuple[bool, str, str]:
    """Run a read-only ``git -C <repo> <args>``. Returns (ok, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, timeout=_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return False, "", "git command timed out"
    return result.returncode == 0, result.stdout, result.stderr


# ─── Porcelain parsing ────────────────────────────────────────────────────────

def _classify(index_ch: str, work_ch: str) -> str:
    """Map a porcelain XY status pair to a human label."""
    if index_ch == "?" and work_ch == "?":
        return "untracked"
    parts: list[str] = []
    if index_ch not in (" ", "?"):
        parts.append("staged")
    if work_ch not in (" ", "?"):
        parts.append("modified")
    return "+".join(parts) if parts else "unknown"


def _parse_porcelain(text: str) -> list[dict]:
    files: list[dict] = []
    for line in text.splitlines():
        if len(line) < 4:
            continue
        index_ch, work_ch, path = line[0], line[1], line[3:]
        # Renames show as "old -> new"; report the current (new) path.
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        files.append({"path": path, "status": _classify(index_ch, work_ch)})
    return files


# ─── git_status ───────────────────────────────────────────────────────────────

def build_git_status_tool(*, owner_agent: str = "vett", default_repo_root: Path | None = None) -> ToolSpec:
    root = default_repo_root or _default_repo_root()

    def handler(args: Mapping[str, Any]) -> Any:
        repo, err = _resolve_repo(args.get("path"), root)
        if err is not None:
            return err
        ok_b, branch, _ = _run_git(repo, "rev-parse", "--abbrev-ref", "HEAD")
        ok_h, head, _ = _run_git(repo, "rev-parse", "--short", "HEAD")
        ok_s, porcelain, serr = _run_git(repo, "status", "--porcelain")
        if not (ok_b and ok_h and ok_s):
            return {"error": "git_failed", "message": serr.strip() or "git status failed"}
        files = _parse_porcelain(porcelain)
        branch_name = branch.strip()
        return {
            "repo_root": str(repo),
            "branch": branch_name if branch_name != "HEAD" else f"(detached at {head.strip()})",
            "head": head.strip(),
            "clean": len(files) == 0,
            "files": files,
        }

    return ToolSpec(
        name="git_status",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "A file or directory inside the repo to inspect. "
                                   "Omit to use the SOVERYN vnext repo.",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Read-only git status. Returns the current branch, HEAD short-sha, "
            "whether the tree is clean, and every changed file with its state "
            "(staged / modified / untracked). Use this to verify not just what a "
            "file says but WHERE it lives — is it committed, modified, on a "
            "feature branch. Never modifies the repo."
        ),
    )


# ─── git_log ──────────────────────────────────────────────────────────────────

def build_git_log_tool(*, owner_agent: str = "vett", default_repo_root: Path | None = None) -> ToolSpec:
    root = default_repo_root or _default_repo_root()

    def handler(args: Mapping[str, Any]) -> Any:
        repo, err = _resolve_repo(args.get("path"), root)
        if err is not None:
            return err
        try:
            max_count = int(args.get("max_count", _DEFAULT_LOG_COUNT))
        except (TypeError, ValueError):
            max_count = _DEFAULT_LOG_COUNT
        max_count = max(1, min(max_count, _MAX_LOG_COUNT))

        git_args = [
            "log", f"--max-count={max_count}", "--date=short",
            f"--pretty=format:%h{_FS}%ad{_FS}%s",
        ]
        # Scope to a specific file when the path points at one inside the repo.
        path_arg = args.get("path")
        if isinstance(path_arg, str) and path_arg.strip():
            p = Path(path_arg).expanduser()
            if p.is_file():
                git_args += ["--", str(p)]

        ok, out, serr = _run_git(repo, *git_args)
        if not ok:
            return {"error": "git_failed", "message": serr.strip() or "git log failed"}
        commits = []
        for line in out.splitlines():
            parts = line.split(_FS)
            if len(parts) == 3:
                commits.append({"sha": parts[0], "date": parts[1], "subject": parts[2]})
        return {"repo_root": str(repo), "commits": commits}

    return ToolSpec(
        name="git_log",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "A file (scopes history to that file) or directory "
                                   "inside the repo. Omit to use the SOVERYN vnext repo.",
                },
                "max_count": {
                    "type": "integer",
                    "description": f"How many recent commits to return (default "
                                   f"{_DEFAULT_LOG_COUNT}, max {_MAX_LOG_COUNT}).",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Read-only git log. Returns recent commits (short-sha, date, subject), "
            "newest first. Pass a file path to see only the commits that touched "
            "that file. Answers 'when was this last changed, and by what.' Never "
            "modifies the repo."
        ),
    )


# ─── git_diff ─────────────────────────────────────────────────────────────────

def build_git_diff_tool(*, owner_agent: str = "vett", default_repo_root: Path | None = None) -> ToolSpec:
    root = default_repo_root or _default_repo_root()

    def handler(args: Mapping[str, Any]) -> Any:
        repo, err = _resolve_repo(args.get("path"), root)
        if err is not None:
            return err
        try:
            max_lines = int(args.get("max_lines", _DEFAULT_DIFF_LINES))
        except (TypeError, ValueError):
            max_lines = _DEFAULT_DIFF_LINES
        max_lines = max(1, max_lines)
        staged = bool(args.get("staged", False))

        git_args = ["diff"]
        if staged:
            git_args.append("--cached")
        path_arg = args.get("path")
        if isinstance(path_arg, str) and path_arg.strip():
            p = Path(path_arg).expanduser()
            if p.is_file():
                git_args += ["--", str(p)]

        ok, out, serr = _run_git(repo, *git_args)
        if not ok:
            return {"error": "git_failed", "message": serr.strip() or "git diff failed"}

        lines = out.splitlines()
        truncated = len(lines) > max_lines
        if truncated:
            shown = lines[:max_lines]
            shown.append(f"... [diff truncated at {max_lines} lines; "
                         f"{len(lines) - max_lines} more]")
            diff_text = "\n".join(shown)
        else:
            diff_text = out.rstrip("\n") if out else ""
        return {
            "repo_root": str(repo),
            "staged": staged,
            "truncated": truncated,
            "diff": diff_text,
        }

    return ToolSpec(
        name="git_diff",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "A file (diffs only that file) or directory inside "
                                   "the repo. Omit to use the SOVERYN vnext repo.",
                },
                "staged": {
                    "type": "boolean",
                    "description": "Diff the staged (index) changes instead of the "
                                   "working tree. Default false.",
                },
                "max_lines": {
                    "type": "integer",
                    "description": f"Cap the diff at this many lines (default "
                                   f"{_DEFAULT_DIFF_LINES}). Output past the cap is "
                                   "truncated with a marker.",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Read-only git diff. Returns the working-tree diff (or the staged diff "
            "with staged=true), capped to a line limit. Pass a file path to diff "
            "just that file. Answers 'what exactly differs from what's committed.' "
            "Never modifies the repo."
        ),
    )


# ─── Registration ─────────────────────────────────────────────────────────────

def register_vett_git_tools(
    registry, *, owner_agent: str = "vett", default_repo_root: Path | None = None
) -> None:
    """Register Vett's three read-only git tools onto the shared registry."""
    registry.register(build_git_status_tool(owner_agent=owner_agent, default_repo_root=default_repo_root))
    registry.register(build_git_log_tool(owner_agent=owner_agent, default_repo_root=default_repo_root))
    registry.register(build_git_diff_tool(owner_agent=owner_agent, default_repo_root=default_repo_root))
