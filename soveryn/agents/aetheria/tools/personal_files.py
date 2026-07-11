"""Aetheria's personal-file browser — bounded read access to Jon's content
directories so she can proactively pick images/docs to send him or
reference. Distinct from Scotty's mechanical filesystem tools (which
scope to the vnext repo): this surface scopes to Jon's content roots —
Pictures, Desktop, Documents, Downloads.

Surfaced 2026-06-05 during signal-images T8 when Jon asked Aetheria to
send him the SOVERYN logo and she had to admit she had no way to list
~/Pictures/ to find a path. Ships the structural answer: she can now
browse the content roots and call signal_send with whatever she picks.

Path safety:
  - Absolute paths only (no surprise CWD resolution).
  - Path must resolve under one of AETHERIA_CONTENT_ROOTS — symlinks
    that escape are rejected post-resolve.
  - No traversal `..` segments accepted in the raw input.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from soveryn.platform.tools.registry import ToolArgError, ToolSpec


AETHERIA_CONTENT_ROOTS: tuple[Path, ...] = (
    (Path.home() / "Pictures").resolve(),
    (Path.home() / "Desktop").resolve(),
    (Path.home() / "Documents").resolve(),
    (Path.home() / "Downloads").resolve(),
)

# Caps tuned for "find something to share" not "ingest a whole tree."
LIST_MAX_ENTRIES = 200
READ_FILE_MAX_BYTES = 256 * 1024  # 256 KB


class PathOutOfContentRootsError(ValueError):
    """Raised when a requested path resolves outside the content allowlist."""


def resolve_within_content_roots(
    user_path: str,
    *,
    roots: tuple[Path, ...] | None = None,
) -> Path:
    """Resolve a user-supplied path against the content-roots allowlist.

    Returns the resolved absolute path on success. Raises
    PathOutOfContentRootsError on any guard failure: non-absolute input,
    `..` segments, or a resolved path that falls outside every allowed
    root.

    `roots=None` resolves at call time against the module-level
    AETHERIA_CONTENT_ROOTS so tests can monkeypatch the default.
    """
    if roots is None:
        roots = AETHERIA_CONTENT_ROOTS
    if not isinstance(user_path, str) or not user_path.strip():
        raise PathOutOfContentRootsError("path must be a non-empty string")
    if not user_path.startswith("/"):
        raise PathOutOfContentRootsError(
            f"path must be absolute (start with '/'): {user_path!r}"
        )
    if ".." in Path(user_path).parts:
        raise PathOutOfContentRootsError(
            f"path contains traversal segment '..': {user_path!r}"
        )
    try:
        resolved = Path(user_path).resolve(strict=False)
    except (OSError, RuntimeError) as e:
        raise PathOutOfContentRootsError(f"could not resolve {user_path!r}: {e}")
    for root in roots:
        if resolved.is_relative_to(root):
            return resolved
    raise PathOutOfContentRootsError(
        f"path {user_path!r} resolves to {resolved} which is outside the "
        f"allowed content roots {tuple(str(r) for r in roots)!r}"
    )


def _content_roots_summary(roots: tuple[Path, ...] | None = None) -> dict:
    """When called with no path, surface what's available at the top level."""
    if roots is None:
        roots = AETHERIA_CONTENT_ROOTS
    summary = []
    for root in roots:
        if not root.exists() or not root.is_dir():
            summary.append({
                "root": str(root),
                "exists": False,
                "entry_count": 0,
            })
            continue
        try:
            count = sum(1 for _ in root.iterdir())
        except OSError:
            count = 0
        summary.append({
            "root": str(root),
            "exists": True,
            "entry_count": count,
        })
    return {"roots": summary, "note": (
        "Call list_personal_files with a specific root path to browse "
        "its contents. Paths must be absolute and resolve under one of "
        "the listed roots."
    )}


def build_list_personal_files_tool(
    *, owner_agent: str = "aetheria",
    roots: tuple[Path, ...] | None = None,
) -> ToolSpec:
    """Bounded directory listing under the given content roots (default:
    Jon's content roots). With no `path` argument, surfaces a summary of
    the available roots. `roots` scopes a non-default owner (e.g. Vett)
    to a specific project directory."""

    def handler(args: Mapping[str, Any]) -> Any:
        path_arg = args.get("path")
        if path_arg is None or (isinstance(path_arg, str) and not path_arg.strip()):
            return _content_roots_summary(roots)
        if not isinstance(path_arg, str):
            raise ToolArgError("path must be a string")
        try:
            resolved = resolve_within_content_roots(path_arg, roots=roots)
        except PathOutOfContentRootsError as e:
            raise ToolArgError(str(e))
        if not resolved.exists():
            raise ToolArgError(f"path {path_arg!r} does not exist")
        if not resolved.is_dir():
            raise ToolArgError(f"path {path_arg!r} is not a directory")
        entries: list[dict[str, Any]] = []
        truncated = False
        for i, child in enumerate(sorted(resolved.iterdir())):
            if i >= LIST_MAX_ENTRIES:
                truncated = True
                break
            kind = (
                "directory" if child.is_dir()
                else "symlink" if child.is_symlink()
                else "file"
            )
            try:
                size_bytes = child.stat().st_size if kind == "file" else None
            except OSError:
                size_bytes = None
            entries.append({
                "name": child.name,
                "kind": kind,
                "size_bytes": size_bytes,
            })
        return {
            "path": str(resolved),
            "entries": entries,
            "count": len(entries),
            "truncated": truncated,
            "max_entries": LIST_MAX_ENTRIES,
        }

    return ToolSpec(
        name="list_personal_files",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Absolute path to list. Must resolve under one of "
                        "Jon's content roots (~/Pictures, ~/Desktop, "
                        "~/Documents, ~/Downloads). Omit to see a summary "
                        "of the available roots."
                    ),
                },
            },
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Browse Jon's personal content directories — Pictures, Desktop, "
            "Documents, Downloads. Use this when you want to find an image "
            "to send him via signal_send, reference a document, or surface "
            "something specific from his workspace. Call with no path to "
            "see what's available; then call again with a root path to "
            "drill into it."
        ),
    )


def build_read_personal_file_tool(
    *, owner_agent: str = "aetheria",
    roots: tuple[Path, ...] | None = None,
) -> ToolSpec:
    """Bounded file read under the given content roots (default: Jon's
    content roots). UTF-8 decoded for text; binary files return a metadata
    stub. `roots` scopes a non-default owner to a specific directory."""

    def handler(args: Mapping[str, Any]) -> Any:
        path_arg = args.get("path", "")
        if not isinstance(path_arg, str):
            raise ToolArgError("path must be a string")
        try:
            resolved = resolve_within_content_roots(path_arg, roots=roots)
        except PathOutOfContentRootsError as e:
            raise ToolArgError(str(e))
        if not resolved.exists():
            raise ToolArgError(f"path {path_arg!r} does not exist")
        if not resolved.is_file():
            raise ToolArgError(f"path {path_arg!r} is not a regular file")
        size = resolved.stat().st_size
        # Sniff binary vs text by extension — binary files get a metadata
        # stub so we don't dump megabytes of image bytes into her context.
        binary_exts = {
            ".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic",
            ".pdf", ".mp4", ".mov", ".mp3", ".m4a", ".wav",
            ".zip", ".tar", ".gz",
        }
        ext = resolved.suffix.lower()
        if ext in binary_exts:
            return {
                "path": str(resolved),
                "size_bytes": size,
                "kind": "binary",
                "extension": ext,
                "content": None,
                "note": (
                    "Binary file — body omitted. Pass the path to "
                    "signal_send to share it with Jon."
                ),
            }
        # Text path
        with resolved.open("rb") as f:
            raw = f.read(READ_FILE_MAX_BYTES + 1)
        truncated = len(raw) > READ_FILE_MAX_BYTES
        if truncated:
            raw = raw[:READ_FILE_MAX_BYTES]
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            content = raw.decode("utf-8", errors="replace")
        return {
            "path": str(resolved),
            "size_bytes": size,
            "kind": "text",
            "content": content,
            "truncated": truncated,
            "max_bytes": READ_FILE_MAX_BYTES,
        }

    return ToolSpec(
        name="read_personal_file",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Absolute path to read. Must resolve under one of "
                        "Jon's content roots. Text files return content "
                        "(UTF-8, up to 256 KB). Binary files (images, PDFs, "
                        "audio, video) return a metadata stub — use the "
                        "path with signal_send to share without reading "
                        "the bytes."
                    ),
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Read a single file from Jon's content directories. Text files "
            "return content; binary files return a metadata stub so you "
            "can share via signal_send without ingesting the bytes."
        ),
    )


def register_personal_files_tools(
    registry, *, owner_agent: str = "aetheria",
    roots: tuple[Path, ...] | None = None,
) -> None:
    """Register both tools for the given agent, optionally scoped to
    specific `roots` (default: Jon's content roots)."""
    registry.register(build_list_personal_files_tool(owner_agent=owner_agent, roots=roots))
    registry.register(build_read_personal_file_tool(owner_agent=owner_agent, roots=roots))
