"""Filesystem read tools for Scotty: read_file + list_directory."""

from __future__ import annotations

import fnmatch
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
        glob_arg = args.get("glob")
        if glob_arg is not None and not isinstance(glob_arg, str):
            raise ToolArgError("glob must be a string")
        sort_arg = args.get("sort") or "name"
        if sort_arg not in ("name", "mtime"):
            raise ToolArgError("sort must be name or mtime")
        children = list(resolved.iterdir())
        if glob_arg:
            children = [c for c in children if fnmatch.fnmatch(c.name, glob_arg)]
        if sort_arg == "mtime":
            children.sort(key=lambda c: c.stat().st_mtime, reverse=True)
        else:
            children.sort(key=lambda c: c.name)
        entries = []
        truncated = False
        for i, child in enumerate(children):
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
                "glob": {
                    "type": "string",
                    "description": (
                        "Optional filename glob (e.g. *.pdf). Applied before "
                        "the entry cap."
                    ),
                },
                "sort": {
                    "type": "string",
                    "enum": ["name", "mtime"],
                    "description": (
                        "name (default, A-Z) or mtime (newest first). Use "
                        "mtime on ~/Downloads so new receipts are not hidden "
                        "behind the 200-entry cap."
                    ),
                },
            },
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            f"List the contents of a directory. Returns up to "
            f"{LIST_DIRECTORY_MAX_ENTRIES} entries. Default sort is name. "
            f"Pass sort=mtime for newest first, glob=*.pdf to filter. "
            f"truncated=true if more remain. Each entry has name, kind, "
            f"size_bytes. Paths outside the project root are rejected."
        ),
    )


# ─── write_file (added 2026-09-22) ──────────────────────────────────────────
# The Messages Kernel had read/list only — no hands. It claimed file builds
# that never landed (the demos/orrery phantom: twice). A builder seat needs
# a write tool whose success is VERIFIED, not asserted.

WRITE_FILE_MAX_BYTES = 256 * 1024  # 256 KB per write; larger means use git


def build_write_file_tool(*, owner_agent: str, root: Path) -> ToolSpec:
    """Verified file write, jailed to `root`.

    The handler never reports success without proof: after writing it
    re-stats the file and reads back the first line. Returns the byte count
    and sha256 prefix so the caller's "done" claim has an artifact behind it.
    """

    def handler(args: Mapping[str, Any]) -> Any:
        import hashlib

        path_arg = args.get("path", "")
        content = args.get("content", "")
        if not isinstance(path_arg, str) or not path_arg.strip():
            raise ToolArgError("path must be a non-empty string")
        if not isinstance(content, str):
            raise ToolArgError("content must be a string")
        # ~ expands to the jail root for the kernel seat — expand BEFORE the
        # jail check so ~/soveryn_vnext/... lands inside the fence. A ~user
        # form (~jon/...) does not expand (no such user) and would fall
        # through as a relative path creating literal "~jon/" directories —
        # refuse any other tilde usage outright.
        if path_arg.startswith("~"):
            import os as _os
            expanded = _os.path.expanduser(path_arg)
            if expanded.startswith("~"):
                raise ToolArgError(
                    f"unknown user in path {path_arg!r} — use a house path"
                )
            path_arg = expanded
        if len(content.encode("utf-8")) > WRITE_FILE_MAX_BYTES:
            raise ToolArgError(
                f"content exceeds {WRITE_FILE_MAX_BYTES} bytes — write it in "
                "parts or via git on the tower"
            )
        try:
            resolved = resolve_within_root(path_arg, root=root, must_exist=False)
        except PathOutOfBoundsError as e:
            raise ToolArgError(str(e))
        if resolved.is_dir():
            raise ToolArgError(f"path {path_arg!r} is a directory")
        resolved.parent.mkdir(parents=True, exist_ok=True)
        try:
            resolved.write_text(content, encoding="utf-8")
        except OSError as e:
            raise ToolArgError(f"write failed: {e}")

        # ── verification: the claim needs an artifact ──
        stat = resolved.stat()
        size = stat.st_size
        expected = len(content.encode("utf-8"))
        readback = resolved.read_text(encoding="utf-8")
        if size != expected or readback != content:
            raise ToolArgError(
                f"write verification FAILED: on disk {size} bytes, "
                f"expected {expected}. The file may be truncated — do not "
                "claim this build is done."
            )
        sha = hashlib.sha256(readback.encode("utf-8")).hexdigest()[:12]
        return {
            "ok": True,
            "path": str(resolved),
            "bytes": size,
            "sha256_12": sha,
            "first_line": (readback.splitlines() or [""])[0][:120],
        }

    return ToolSpec(
        name="write_file",
        owner=owner_agent,
        description=(
            "Write a text file (path jailed to the house root). Creates parent "
            "directories. Returns bytes written, sha256 prefix, and the first "
            "line — verify these before claiming the file is built."
        ),
        schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path (jailed to house root)"},
                "content": {"type": "string", "description": "Full file content"},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
        handler=handler,
    )
