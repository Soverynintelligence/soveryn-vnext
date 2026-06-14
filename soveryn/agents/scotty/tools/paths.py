"""Path allow-list helpers for Scotty's mechanical tools.

Every file system operation Scotty performs goes through
resolve_within_root() — symlink escapes, absolute paths outside the
root, and `..` traversal that lands outside are all rejected.
"""

from __future__ import annotations

import os
from pathlib import Path


SCOTTY_PROJECT_ROOT = (Path.home() / "soveryn_vnext").resolve()


class PathOutOfBoundsError(ValueError):
    """Raised when a requested path resolves outside SCOTTY_PROJECT_ROOT."""


def resolve_within_root(
    user_path: str,
    *,
    root: Path = SCOTTY_PROJECT_ROOT,
    must_exist: bool = False,
) -> Path:
    """Resolve `user_path` to an absolute Path under `root`.

    `user_path` can be relative (interpreted against root) or absolute.
    Symlink resolution happens first; if the resolved target falls
    outside `root`, PathOutOfBoundsError is raised. If `must_exist` is
    True and the resolved path doesn't exist, FileNotFoundError is
    raised. Otherwise the path is returned even if it doesn't exist
    (caller decides what to do — useful for create-if-missing flows we
    don't ship yet).
    """
    if not isinstance(user_path, str) or not user_path.strip():
        raise PathOutOfBoundsError("path must be a non-empty string")
    candidate = Path(user_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve(strict=False)
    except (OSError, RuntimeError) as e:
        raise PathOutOfBoundsError(f"could not resolve {user_path!r}: {e}")
    # Path.is_relative_to was added in 3.9; we're on 3.11. On linux it doesn't
    # raise — it just returns False for paths under a different root.
    if not resolved.is_relative_to(root):
        raise PathOutOfBoundsError(
            f"path {user_path!r} resolves to {resolved} which is outside "
            f"the allowed root {root}"
        )
    if must_exist and not resolved.exists():
        raise FileNotFoundError(f"path {user_path!r} does not exist")
    return resolved
