"""write_file tool for Scotty.

Creates a NEW file. This is the counterpart to edit_file, which modifies an
existing one — between them Scotty can author code as well as amend it.

Why this exists (2026-07-22): the delegation pipeline failed 8 out of 8 tasks,
every one with an empty diff. Every task was "implement a module", i.e. create
new files, and Scotty had no tool that could create one. ``edit_file`` requires
``old_string`` and refuses paths that do not exist (deliberately — see edit.py).
His workaround, ``run_command python -c``, is refused by the arbitrary-code
guard (also deliberately). Neither guard was wrong; the gap was between them.
He diagnosed it himself mid-run: "The edit_file tool requires the file to
already exist."

Hard guards:
  - Path resolves under ``root`` (no /etc, no $HOME, no ../ escape).
  - CREATE ONLY — refuses if the path already exists, and points at edit_file.
    Overwriting whole files is precisely the clobbering that edit_file's
    uniqueness guard exists to prevent; write_file must not smuggle it back in.
  - Parent directories are created, but only inside ``root`` (a delegated task
    scoped to ``soveryn/pond_builder/`` needs to make the package first).
  - Content must be a UTF-8 string, capped at WRITE_FILE_MAX_BYTES.

Pair with git_status + git_diff to verify, and git_restore_file to roll back.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from soveryn.agents.scotty.tools.paths import (
    SCOTTY_PROJECT_ROOT,
    PathOutOfBoundsError,
    resolve_within_root,
)
from soveryn.platform.tools.registry import ToolArgError, ToolSpec


WRITE_FILE_MAX_BYTES = 256 * 1024     # 256 KB — matches edit_file's cap


def build_write_file_tool(*, owner_agent: str, root: Path = SCOTTY_PROJECT_ROOT) -> ToolSpec:
    """Create a new file with the given content, bounded to ``root``.

    ``root`` bounds every path exactly as it does for edit_file: writes resolve
    under it and paths escaping it are rejected. Defaults to the live repo;
    delegated execution passes the task worktree so Scotty's new files land in
    isolation, never the live tree.
    """

    def handler(args: Mapping[str, Any]) -> Any:
        path_arg = args.get("path", "")
        if not isinstance(path_arg, str) or not path_arg.strip():
            raise ToolArgError("path must be a non-empty string")
        content = args.get("content", "")
        if not isinstance(content, str):
            raise ToolArgError("content must be a string")

        encoded = content.encode("utf-8")
        if len(encoded) > WRITE_FILE_MAX_BYTES:
            raise ToolArgError(
                f"content exceeds the {WRITE_FILE_MAX_BYTES // 1024} KB cap — "
                f"split the file or write it in parts"
            )

        try:
            resolved = resolve_within_root(path_arg, root=root, must_exist=False)
        except PathOutOfBoundsError as e:
            raise ToolArgError(str(e))

        if resolved.exists():
            raise ToolArgError(
                f"{path_arg!r} already exists — write_file creates new files only. "
                f"Use edit_file to modify it."
            )

        # Parent dirs are created, but resolve_within_root has already proven the
        # target is inside root, so this cannot mkdir outside the boundary.
        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ToolArgError(f"could not create parent directory for {path_arg!r}: {e}")

        resolved.write_text(content, encoding="utf-8")
        return {
            "path": str(resolved),
            "created": True,
            "bytes_written": len(encoded),
        }

    return ToolSpec(
        name="write_file",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Path of the NEW file, relative to the project root or "
                        "absolute. Must resolve under the project root. Parent "
                        "directories are created as needed. Must NOT already exist."
                    ),
                },
                "content": {
                    "type": "string",
                    "description": "Full UTF-8 contents of the new file.",
                },
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Create a NEW file with the given content. Use this to author files "
            "that do not exist yet; use edit_file to modify files that do. "
            "Refuses to overwrite an existing path. Parent directories are "
            "created automatically. Paths outside the project root are rejected. "
            f"Content capped at {WRITE_FILE_MAX_BYTES // 1024} KB. After writing, "
            "use git_status and git_diff to verify."
        ),
    )
