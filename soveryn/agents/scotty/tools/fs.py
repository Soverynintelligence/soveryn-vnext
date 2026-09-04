"""Filesystem read tools for Scotty: read_file + list_directory."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from soveryn.agents.scotty.tools.paths import (
    PathOutOfBoundsError,
    SCOTTY_PROJECT_ROOT,
    resolve_within_root,
)
from soveryn.platform.tools.registry import ToolArgError, ToolSpec


# Caps — small enough to avoid context exhaustion, large enough to be useful.
# 40 KB ≈ ~10K tokens: a single read fits inside the 32K server window
# alongside the ~13K base prompt + 8K history budget (see startup
# context_window wiring). Larger files return truncated=True; read in parts.
READ_FILE_MAX_BYTES = 40 * 1024             # 40 KB
# Spill files are recovery pointers. Dumping them hits SPILL_TRIGGER (~8k)
# and the stub used to say "read_file that path" — infinite cascade.
SPILL_REREAD_MAX_BYTES = 2_400
LIST_DIRECTORY_MAX_ENTRIES = 200


def build_read_file_tool(
    *, owner_agent: str, root: Path = SCOTTY_PROJECT_ROOT
) -> ToolSpec:
    """Bounded file read. Returns up to READ_FILE_MAX_BYTES of text.

    `root` fences every read; defaults to the vnext repo. Vett is
    registered with a wider root (the home directory) so she can view
    files across all SOVERYN projects, not just the vnext repo.
    """

    def handler(args: Mapping[str, Any]) -> Any:
        path_arg = args.get("path", "")
        if not isinstance(path_arg, str):
            raise ToolArgError("path must be a string")
        try:
            resolved = resolve_within_root(path_arg, root=root, must_exist=True)
        except PathOutOfBoundsError as e:
            raise ToolArgError(str(e))
        except FileNotFoundError as e:
            raise ToolArgError(str(e))
        if not resolved.is_file():
            raise ToolArgError(f"path {path_arg!r} is not a regular file")
        try:
            offset = int(args.get("offset") or 0)
        except (TypeError, ValueError):
            offset = 0
        if offset < 0:
            offset = 0
        is_spill = "tool_spill" in resolved.as_posix()
        cap = SPILL_REREAD_MAX_BYTES if is_spill else READ_FILE_MAX_BYTES
        try:
            requested = int(args.get("max_bytes") or cap)
        except (TypeError, ValueError):
            requested = cap
        max_bytes = max(1, min(requested, cap))
        size = resolved.stat().st_size
        with resolved.open("rb") as f:
            if offset:
                f.seek(min(offset, size))
            raw = f.read(max_bytes + 1)
        truncated = len(raw) > max_bytes or (offset + min(len(raw), max_bytes)) < size
        if len(raw) > max_bytes:
            raw = raw[:max_bytes]
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            content = raw.decode("utf-8", errors="replace")
        out = {
            "path": str(resolved),
            "size_bytes": size,
            "offset": offset,
            "content": content,
            "truncated": truncated,
            "max_bytes": max_bytes,
        }
        if is_spill:
            out["spill_reread"] = True
            out["hint"] = (
                "This is a lean-tail spill file. Do not read_file it again. "
                "Page the original path with offset/max_bytes if you need a slice."
            )
        return out

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
                "offset": {
                    "type": "integer",
                    "description": "Byte offset to start reading (default 0).",
                },
                "max_bytes": {
                    "type": "integer",
                    "description": (
                        f"Max bytes to return (capped at {READ_FILE_MAX_BYTES})."
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
            f"is larger. Pass offset/max_bytes to page. Do not read_file paths "
            f"under tool_spill/ — those are already spilled stubs. UTF-8 decoded "
            f"(replacement on bad bytes). Paths outside the project root are rejected."
        ),
    )


def build_list_directory_tool(
    *, owner_agent: str, root: Path = SCOTTY_PROJECT_ROOT
) -> ToolSpec:
    """Bounded directory listing. `root` fences every listing; defaults to
    the vnext repo. Vett gets a wider root (home) for cross-project view."""

    def handler(args: Mapping[str, Any]) -> Any:
        path_arg = args.get("path", ".")
        if not isinstance(path_arg, str):
            raise ToolArgError("path must be a string")
        try:
            resolved = resolve_within_root(path_arg, root=root, must_exist=True)
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
