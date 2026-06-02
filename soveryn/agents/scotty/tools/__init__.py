"""Scotty's bounded mechanical tools.

Five read-only tools that let Scotty observe the vnext repo's state:
- read_file:        bounded read of a single file
- list_directory:   bounded directory listing
- git_status:       porcelain-format git status
- git_diff:         unstaged or staged diff, line-capped
- run_pytest:       run pytest on a bounded path with a hard timeout

All five enforce a path allow-list rooted at SCOTTY_PROJECT_ROOT (the
vnext repo). Size, time, and output caps are applied per tool. No write
tools, no arbitrary shell, no scope inference — Scotty observes and
reports; Aetheria decides; Jon authorizes.

Design intent matches the 2026-05-22 bounded-executor scaffolding:
Detect -> Decide -> (bounded) Fix -> Verify -> Rollback. This phase
ships Detect + Verify; Fix and Rollback gate on the active-write-tools
phase (still queued).
"""

from soveryn.agents.scotty.tools.fs import (
    build_read_file_tool,
    build_list_directory_tool,
)
from soveryn.agents.scotty.tools.git import (
    build_git_status_tool,
    build_git_diff_tool,
)
from soveryn.agents.scotty.tools.pytest_runner import build_run_pytest_tool
from soveryn.agents.scotty.tools.paths import (
    SCOTTY_PROJECT_ROOT,
    PathOutOfBoundsError,
    resolve_within_root,
)
from soveryn.platform.tools.registry import ToolRegistry


def register_scotty_tools(registry: ToolRegistry) -> None:
    """Register Scotty's five bounded mechanical tools."""
    registry.register(build_read_file_tool(owner_agent="scotty"))
    registry.register(build_list_directory_tool(owner_agent="scotty"))
    registry.register(build_git_status_tool(owner_agent="scotty"))
    registry.register(build_git_diff_tool(owner_agent="scotty"))
    registry.register(build_run_pytest_tool(owner_agent="scotty"))


__all__ = [
    "register_scotty_tools",
    "build_read_file_tool",
    "build_list_directory_tool",
    "build_git_status_tool",
    "build_git_diff_tool",
    "build_run_pytest_tool",
    "SCOTTY_PROJECT_ROOT",
    "PathOutOfBoundsError",
    "resolve_within_root",
]
