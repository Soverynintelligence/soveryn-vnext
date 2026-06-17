"""Filesystem read tools for Scotty: read_file + list_directory."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from soveryn.agents.scotty.tools.paths import (
    PathOutOfBoundsError,
    resolve_within_root,
)
from soveryn.platform.tools.registry import ToolArgError, ToolSpec


# Caps — small enough to avoid context exhaustion, large enough to be useful.
# 40 KB ≈ ~10K tokens: a single read fits inside the 32K server window
# alongside the ~13K base prompt + 8K history budget (see startup
# context_window wiring). Larger files return truncated=True; read in parts.
READ_FILE_MAX_BYTES = 40 * 1024             # 40 KB
LIST_DIRECTORY_MAX_ENTRIES = 200


def build_read_file_tool(*, owner_agent: str) -> ToolSpec:
    """Bounded file read. Returns up to READ_FILE_MAX_BYTES of text."""

    def handler(args: Mapping[str, Any]) -> Any:
        path_arg = args.get("path", "")
        if not isinstance(path_arg, str):
            raise ToolArgError("path must be a string")
        try:
            resolved = resolve_within_root(path_arg, must_exist=True)
        except PathOutOfBoundsError as e:
            raise ToolArgError(str(e))
        except FileNotFoundError as e:
            raise ToolArgError(str(e))
        if not resolved.is_file():
            raise ToolArgError(f"path {path_arg!r} is not a regular file")
        size = resolved.stat().st_size
        with resolved.open("rb") as f:
            raw = f.read(READ_FILE_MAX_BYTES + 1)
        truncated = len(raw) > READ_FILE_MAX_BYTES
        if truncated:
            raw = raw[:READ_FILE_MAX_BYTES]
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            # Fall back to replacement so the model sees something useful.
            content = raw.decode("utf-8", errors="replace")
        return {
            "path": str(resolved),
            "size_bytes": size,
            "content": content,
            "truncated": truncated,
            "max_bytes": READ_FILE_MAX_BYTES,
        }

    return ToolSpec(
        name="read_file",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Path to read, relative to the vnext repo root or "
                        "absolute. Must resolve under the project root; symlink "
                        "escapes are rejected."
                    ),
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            f"Read a single file from the vnext repository. Returns up to "
            f"{READ_FILE_MAX_BYTES // 1024} KB; sets truncated=true if the file "
            f"is larger than that. UTF-8 decoded (with replacement on bad bytes). "
            f"Paths outside the project root are rejected."
        ),
    )


def build_list_directory_tool(*, owner_agent: str) -> ToolSpec:
    """Bounded directory listing."""

    def handler(args: Mapping[str, Any]) -> Any:
        path_arg = args.get("path", ".")
        if not isinstance(path_arg, str):
            raise ToolArgError("path must be a string")
        try:
            resolved = resolve_within_root(path_arg, must_exist=True)
        except PathOutOfBoundsError as e:
            raise ToolArgError(str(e))
        except FileNotFoundError as e:
            raise ToolArgError(str(e))
        if not resolved.is_dir():
            raise ToolArgError(f"path {path_arg!r} is not a directory")
        entries = []
        truncated = False
        # Sort for deterministic output; matches `ls` default.
        for i, child in enumerate(sorted(resolved.iterdir())):
            if i >= LIST_DIRECTORY_MAX_ENTRIES:
                truncated = True
                break
            kind = "directory" if child.is_dir() else ("symlink" if child.is_symlink() else "file")
            entries.append({
                "name": child.name,
                "kind": kind,
                "size_bytes": (child.stat().st_size if kind == "file" else None),
            })
        return {
            "path": str(resolved),
            "entries": entries,
            "count": len(entries),
            "truncated": truncated,
            "max_entries": LIST_DIRECTORY_MAX_ENTRIES,
        }

    return ToolSpec(
        name="list_directory",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Directory path. Defaults to vnext repo root if omitted."
                    ),
                },
            },
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            f"List the contents of a directory in the vnext repository. Returns "
            f"up to {LIST_DIRECTORY_MAX_ENTRIES} entries sorted by name; sets "
            f"truncated=true if the directory has more. Each entry has name, "
            f"kind (file/directory/symlink), and size_bytes (for files only). "
            f"Paths outside the project root are rejected."
        ),
    )
