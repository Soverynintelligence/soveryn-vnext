"""edit_file tool for Scotty.

Surgical edits via old_string → new_string with a uniqueness guard.
Pattern mirrors Claude Code's Edit tool: Scotty produces enough context
in old_string to disambiguate, and the tool refuses if the match is
ambiguous (>1 occurrence) or missing (0 occurrences). This is the
safety property — the model can't "patch line 50 and accidentally
clobber lines 1-49" because the substitution is anchored in textual
context, not a line number.

Hard guards:
  - Path resolves under SCOTTY_PROJECT_ROOT (no /etc, no $HOME).
  - Target must already exist (no create-new in this tool).
  - old_string must appear exactly once.
  - new_string must differ from old_string (no-op edits refused so
    the audit log isn't polluted with phantom mutations).
  - Post-edit file size capped at EDIT_FILE_MAX_BYTES.

Pair with git_status + git_diff to verify your own edit, and
git_restore_file to roll back.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from soveryn.agents.scotty.tools.paths import (
    PathOutOfBoundsError,
    resolve_within_root,
)
from soveryn.platform.tools.registry import ToolArgError, ToolSpec


EDIT_FILE_MAX_BYTES = 256 * 1024     # 256 KB — post-edit content size cap
OLD_STRING_MIN_LEN = 1                # at least one char; uniqueness check does the rest


def build_edit_file_tool(*, owner_agent: str) -> ToolSpec:
    """Bounded write via unique old_string → new_string substitution."""

    def handler(args: Mapping[str, Any]) -> Any:
        path_arg = args.get("path", "")
        if not isinstance(path_arg, str) or not path_arg.strip():
            raise ToolArgError("path must be a non-empty string")
        old_string = args.get("old_string", "")
        new_string = args.get("new_string", "")
        if not isinstance(old_string, str) or len(old_string) < OLD_STRING_MIN_LEN:
            raise ToolArgError("old_string must be a non-empty string")
        if not isinstance(new_string, str):
            raise ToolArgError("new_string must be a string (use \"\" to delete)")
        if old_string == new_string:
            raise ToolArgError("old_string and new_string are identical — no-op edit refused")

        try:
            resolved = resolve_within_root(path_arg, must_exist=True)
        except PathOutOfBoundsError as e:
            raise ToolArgError(str(e))
        except FileNotFoundError as e:
            raise ToolArgError(str(e))
        if not resolved.is_file():
            raise ToolArgError(f"path {path_arg!r} is not a regular file")

        try:
            original = resolved.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            raise ToolArgError(
                f"refusing to edit {path_arg!r}: not UTF-8 ({e})"
            )

        occurrence_count = original.count(old_string)
        if occurrence_count == 0:
            raise ToolArgError(
                f"old_string not found in {path_arg!r} — "
                f"include more surrounding context if the match is in the file"
            )
        if occurrence_count > 1:
            raise ToolArgError(
                f"old_string matches {occurrence_count} locations in {path_arg!r}; "
                f"include more surrounding context to make the match unique"
            )

        updated = original.replace(old_string, new_string, 1)
        if len(updated.encode("utf-8")) > EDIT_FILE_MAX_BYTES:
            raise ToolArgError(
                f"resulting file would exceed the {EDIT_FILE_MAX_BYTES // 1024} KB "
                f"cap — split the edit or refactor smaller"
            )

        resolved.write_text(updated, encoding="utf-8")
        return {
            "path": str(resolved),
            "edited": True,
            "occurrences_replaced": 1,
            "bytes_before": len(original.encode("utf-8")),
            "bytes_after": len(updated.encode("utf-8")),
        }

    return ToolSpec(
        name="edit_file",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Path to edit, relative to the vnext repo root or absolute. "
                        "Must resolve under the project root; must already exist."
                    ),
                },
                "old_string": {
                    "type": "string",
                    "description": (
                        "Exact text to replace. Must appear EXACTLY ONCE in the file "
                        "— include enough surrounding context to disambiguate."
                    ),
                },
                "new_string": {
                    "type": "string",
                    "description": (
                        "Replacement text. Use \"\" to delete the old_string. "
                        "Must differ from old_string."
                    ),
                },
            },
            "required": ["path", "old_string", "new_string"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Surgically edit a file by replacing old_string with new_string. "
            "old_string must match EXACTLY ONCE — include enough surrounding "
            "context to disambiguate. After editing, use git_status and "
            "git_diff to verify; use git_restore_file to roll back. Paths "
            f"outside the project root are rejected. Result size capped at "
            f"{EDIT_FILE_MAX_BYTES // 1024} KB."
        ),
    )
