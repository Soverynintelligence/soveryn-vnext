"""Local image compositor — drop an overlay onto a base PNG.

House desk tool for Eve: template/base + overlay at (x, y) → PNG.
Not Canva-Connect. Never writes outside the caller-supplied media root.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ComposeResult:
    ok: bool
    path: str | None = None
    miss: str | None = None
    width: int | None = None
    height: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "path": self.path,
            "miss": self.miss,
            "width": self.width,
            "height": self.height,
        }


def _open_rgba(path: Path):
    from PIL import Image

    img = Image.open(path)
    return img.convert("RGBA")


def would_clip(
    base_size: tuple[int, int],
    overlay_size: tuple[int, int],
    x: int,
    y: int,
) -> bool:
    bw, bh = base_size
    ow, oh = overlay_size
    return x < 0 or y < 0 or (x + ow) > bw or (y + oh) > bh


def compose_overlay(
    base_path: Path,
    overlay_path: Path,
    *,
    x: int,
    y: int,
    width: int | None = None,
    height: int | None = None,
    clip: bool = False,
    dest: Path,
) -> ComposeResult:
    """Paste overlay onto base at (x, y) and write dest as PNG."""
    if not base_path.is_file():
        return ComposeResult(ok=False, miss="file_not_found", path=str(base_path))
    if not overlay_path.is_file():
        return ComposeResult(ok=False, miss="file_not_found", path=str(overlay_path))

    try:
        base = _open_rgba(base_path)
        overlay = _open_rgba(overlay_path)
    except OSError:
        return ComposeResult(ok=False, miss="unreadable")

    if width is not None or height is not None:
        ow, oh = overlay.size
        tw = int(width) if width is not None else ow
        th = int(height) if height is not None else oh
        if tw <= 0 or th <= 0:
            return ComposeResult(ok=False, miss="invalid_size")
        from PIL import Image

        overlay = overlay.resize((tw, th), Image.Resampling.LANCZOS)

    if would_clip(base.size, overlay.size, x, y) and not clip:
        return ComposeResult(ok=False, miss="would_clip")

    base.paste(overlay, (x, y), overlay)
    dest.parent.mkdir(parents=True, exist_ok=True)
    base.save(dest, format="PNG")
    return ComposeResult(
        ok=True,
        path=str(dest.resolve()),
        width=base.size[0],
        height=base.size[1],
    )
