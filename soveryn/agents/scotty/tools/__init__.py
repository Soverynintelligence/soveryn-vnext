"""Scotty's bounded mechanical tools.

Eight tools across observe / fix / verify / rollback:

Observe (read-only):
- read_file:        bounded read of a single file
- list_directory:   bounded directory listing
- git_status:       porcelain-format git status
- git_diff:         unstaged or staged diff, line-capped

Fix (bounded write):
- edit_file:        surgical old_string → new_string with uniqueness guard
- run_command:      allow-listed executable + args list (NOT a shell)

Verify:
- run_pytest:       run pytest on a bounded path with a hard timeout

Rollback:
- git_restore_file: discard unstaged changes for a tracked file
                    (refuses if staged changes would be lost)

All enforce a path allow-list rooted at SCOTTY_PROJECT_ROOT (the vnext
repo). Size, time, and output caps are applied per tool. Subprocess
calls are arg-list only with shell=False — no shell metacharacters get
interpreted regardless of what Scotty emits.

Operating model: Detect → Decide → (bounded) Fix → Verify → Rollback.
With the write tools added 2026-06-04, the full loop is now available.
Aetheria decides; Scotty executes within these bounds; Jon authorizes
expansions of the executable allow-list.
"""

from soveryn.agents.scotty.tools.fs import (
    build_read_file_tool,
    build_list_directory_tool,
)
from soveryn.agents.scotty.tools.git import (
    build_git_status_tool,
    build_git_diff_tool,
    build_git_restore_file_tool,
)
from soveryn.agents.scotty.tools.edit import build_edit_file_tool
from soveryn.agents.scotty.tools.run_command import build_run_command_tool
from soveryn.agents.scotty.tools.pytest_runner import build_run_pytest_tool
from soveryn.agents.scotty.tools.paths import (
    SCOTTY_PROJECT_ROOT,
    PathOutOfBoundsError,
    resolve_within_root,
)
from soveryn.platform.tools.registry import ToolRegistry


def register_scotty_tools(registry: ToolRegistry) -> None:
    """Register Scotty's bounded mechanical tools (observe + fix + verify + rollback)."""
    # Observe
    registry.register(build_read_file_tool(owner_agent="scotty"))
    registry.register(build_list_directory_tool(owner_agent="scotty"))
    registry.register(build_git_status_tool(owner_agent="scotty"))
    registry.register(build_git_diff_tool(owner_agent="scotty"))
    # Fix
    registry.register(build_edit_file_tool(owner_agent="scotty"))
    registry.register(build_run_command_tool(owner_agent="scotty"))
    # Verify
    registry.register(build_run_pytest_tool(owner_agent="scotty"))
    # Rollback
    registry.register(build_git_restore_file_tool(owner_agent="scotty"))


__all__ = [
    "register_scotty_tools",
    "build_read_file_tool",
    "build_list_directory_tool",
    "build_git_status_tool",
    "build_git_diff_tool",
    "build_git_restore_file_tool",
    "build_edit_file_tool",
    "build_run_command_tool",
    "build_run_pytest_tool",
    "SCOTTY_PROJECT_ROOT",
    "PathOutOfBoundsError",
    "resolve_within_root",
]
