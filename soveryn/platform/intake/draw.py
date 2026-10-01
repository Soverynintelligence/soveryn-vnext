"""Local drawing primitives — canvas, rect, text → PNG.

House desk tools for Eve. Not Canva. Never writes outside the
caller-supplied dest path. Hex colors are arguments; no brand palette
is baked in.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")

_FONT_FILES: dict[str, tuple[Path, ...]] = {
    "serif": (
        Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"),
        Path("/usr/share/fonts/TTF/DejaVuSerif.ttf"),
    ),
    "sans": (
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/TTF/DejaVuSans.ttf"),
    ),
    "serif_italic": (
        Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf"),
        Path("/usr/share/fonts/TTF/DejaVuSerif-Italic.ttf"),
    ),
}


@dataclass(frozen=True)
class DrawResult:
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


def parse_hex_color(value: str) -> tuple[int, int, int]:
    """Parse ``#RGB`` or ``#RRGGBB`` (case insensitive). No ``rgb()`` tuples."""
    if not isinstance(value, str):
        raise ValueError("hex color must be a #RGB or #RRGGBB string")
    raw = value.strip()
    if not raw.startswith("#"):
        raise ValueError("hex color must start with #")
    body = raw[1:]
    if len(body) == 3 and all(c in _HEX_DIGITS for c in body):
        return (
            int(body[0] * 2, 16),
            int(body[1] * 2, 16),
            int(body[2] * 2, 16),
        )
    if len(body) == 6 and all(c in _HEX_DIGITS for c in body):
        return (
            int(body[0:2], 16),
            int(body[2:4], 16),
            int(body[4:6], 16),
        )
    raise ValueError("hex color must be #RGB or #RRGGBB")


def resolve_font(kind: str, size: int):
    """Liberation, then DejaVu, then PIL default. Never require Georgia."""
    from PIL import ImageFont

    for path in _FONT_FILES.get(kind, ()):
        if path.is_file():
            try:
                return ImageFont.truetype(str(path), size=size)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def make_solid_canvas(
    dest: Path,
    *,
    width: int,
    height: int,
    fill: tuple[int, int, int],
) -> DrawResult:
    """Write a solid RGB PNG of ``width`` × ``height`` filled with ``fill``."""
    from PIL import Image

    dest.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (width, height), fill)
    img.save(dest, format="PNG")
    return DrawResult(
        ok=True,
        path=str(dest.resolve()),
        width=width,
        height=height,
    )


def _open_rgb(path: Path):
    from PIL import Image

    return Image.open(path).convert("RGB")


def _rect_fully_outside(
    canvas: tuple[int, int],
    x: int,
    y: int,
    width: int,
    height: int,
) -> bool:
    cw, ch = canvas
    return x + width <= 0 or y + height <= 0 or x >= cw or y >= ch


def draw_rectangle(
    src: Path,
    dest: Path,
    *,
    x: int,
    y: int,
    width: int,
    height: int,
    fill: tuple[int, int, int] | None = None,
    outline: tuple[int, int, int] | None = None,
    stroke: int = 1,
    radius: int = 0,
) -> DrawResult:
    """Draw a rectangle onto ``src`` and write a new PNG at ``dest``.

    A rect that extends past the canvas is clipped. A rect that sits
    fully outside returns ``miss=would_clip`` (unlike a partial overhang).
    """
    if not src.is_file():
        return DrawResult(ok=False, miss="file_not_found", path=str(src))
    try:
        img = _open_rgb(src)
    except OSError:
        return DrawResult(ok=False, miss="unreadable")

    if _rect_fully_outside(img.size, x, y, width, height):
        return DrawResult(ok=False, miss="would_clip")

    from PIL import ImageDraw

    draw = ImageDraw.Draw(img)
    box = [x, y, x + width, y + height]
    kwargs: dict[str, Any] = {}
    if fill is not None:
        kwargs["fill"] = fill
    if outline is not None:
        kwargs["outline"] = outline
        kwargs["width"] = stroke
    max_radius = max(0, min(width, height) // 2)
    use_radius = min(max(0, radius), max_radius)
    if use_radius > 0:
        draw.rounded_rectangle(box, radius=use_radius, **kwargs)
    else:
        draw.rectangle(box, **kwargs)

    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, format="PNG")
    return DrawResult(
        ok=True,
        path=str(dest.resolve()),
        width=img.size[0],
        height=img.size[1],
    )


def _measure_width(font, text: str) -> int:
    if hasattr(font, "getlength"):
        try:
            return int(font.getlength(text))
        except Exception:
            pass
    bbox = font.getbbox(text)
    return int(bbox[2] - bbox[0])


def wrap_text(text: str, font, max_width: int) -> str:
    """Word-wrap ``text`` to ``max_width`` pixels. Existing newlines stay."""
    parts: list[str] = []
    for para in text.split("\n"):
        words = para.split()
        if not words:
            parts.append("")
            continue
        current = words[0]
        for word in words[1:]:
            trial = f"{current} {word}"
            if _measure_width(font, trial) <= max_width:
                current = trial
            else:
                parts.append(current)
                current = word
        parts.append(current)
    return "\n".join(parts)


def _anchor_xy(
    align: str,
    x: int,
    y: int,
    bbox: tuple[int, int, int, int],
) -> tuple[int, int]:
    left, top, right, _bottom = bbox
    if align == "center":
        dx = x - (left + right) / 2
    elif align == "right":
        dx = x - right
    else:
        dx = x - left
    return int(dx), int(y - top)


def draw_text_on_image(
    src: Path,
    dest: Path,
    *,
    text: str,
    x: int,
    y: int,
    size: int,
    color: tuple[int, int, int],
    font_kind: str = "serif",
    align: str = "left",
    max_width: int | None = None,
    font=None,
) -> DrawResult:
    """Draw text onto ``src`` and write a new PNG at ``dest``.

    ``(x, y)`` is the top of the text box; ``align`` sets the horizontal
    anchor (left edge / midpoint / right edge). ``font`` is injectable
    so tests do not depend on a specific file path.
    """
    if not src.is_file():
        return DrawResult(ok=False, miss="file_not_found", path=str(src))
    try:
        img = _open_rgb(src)
    except OSError:
        return DrawResult(ok=False, miss="unreadable")

    from PIL import ImageDraw

    loaded = font if font is not None else resolve_font(font_kind, size)
    rendered = wrap_text(text, loaded, max_width) if max_width is not None else text
    draw = ImageDraw.Draw(img)
    bbox = draw.multiline_textbbox((0, 0), rendered, font=loaded, align=align)
    tx, ty = _anchor_xy(align, x, y, bbox)
    draw.multiline_text((tx, ty), rendered, font=loaded, fill=color, align=align)

    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, format="PNG")
    return DrawResult(
        ok=True,
        path=str(dest.resolve()),
        width=img.size[0],
        height=img.size[1],
    )
