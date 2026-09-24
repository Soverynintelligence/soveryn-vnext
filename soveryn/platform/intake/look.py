"""Downscale house-disk photos so Eve can see them on a vision turn.

Filenames (IMG_6061) do not describe the frame. look_at encodes a
thumbnail as a data: URL; AgentLoop splices those onto the current user
turn. The tool JSON lists names only — never the bytes.
"""

from __future__ import annotations

import base64
from hashlib import md5
from io import BytesIO
from pathlib import Path

_IMG_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MAX_EDGE = 1024
JPEG_QUALITY = 72
MAX_FILES = 8


def collect_photo_paths(
    target: Path,
    *,
    pick: str | None = None,
    max_files: int = MAX_FILES,
) -> list[Path]:
    """Files in `target`, or (if a directory) its images plus one-level children.

    Dedupes byte-identical copies. `pick` is comma-separated filename
    fragments, in order (same rule as make_collage).
    """
    files = _list_images(target)
    files = _pick(files, pick)
    cap = max(1, min(int(max_files), MAX_FILES))
    return files[:cap]


def encode_for_vision(path: Path) -> str:
    """EXIF-aware RGB JPEG thumbnail as a data:image/jpeg URL."""
    from PIL import Image, ImageOps

    im = Image.open(path)
    im = ImageOps.exif_transpose(im).convert("RGB")
    im.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
    buf = BytesIO()
    im.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def find_side_dir(root: Path, side: str) -> Path | None:
    """First subdirectory whose name contains `side` (e.g. before / after)."""
    needle = side.strip().lower()
    if not needle or not root.is_dir():
        return None
    for child in sorted(root.iterdir()):
        if child.is_dir() and needle in child.name.lower():
            return child
    return None


def _list_images(target: Path) -> list[Path]:
    if target.is_file():
        if target.suffix.lower() in _IMG_SUFFIXES:
            return [target]
        return []
    if not target.is_dir():
        return []
    found: list[Path] = []
    seen: set[str] = set()

    def _add(path: Path) -> None:
        if not path.is_file() or path.suffix.lower() not in _IMG_SUFFIXES:
            return
        digest = md5(path.read_bytes()).hexdigest()
        if digest in seen:
            return
        seen.add(digest)
        found.append(path)

    for child in sorted(target.iterdir()):
        if child.is_file():
            _add(child)
        elif child.is_dir():
            for nested in sorted(child.iterdir()):
                _add(nested)
    return found


def _pick(files: list[Path], spec: str | None) -> list[Path]:
    if not spec or not spec.strip():
        return files
    out: list[Path] = []
    for token in [s.strip() for s in spec.split(",") if s.strip()]:
        for f in files:
            if token.lower() in f.name.lower() and f not in out:
                out.append(f)
                break
    return out
