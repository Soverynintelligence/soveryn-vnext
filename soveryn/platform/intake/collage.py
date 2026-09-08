"""CWG Instagram before/after collage (1080×1350). Not a generic grid."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import md5
from pathlib import Path
from typing import Any

W, H = 1080, 1350
BG = (12, 35, 30)
CREAM = (239, 230, 210)
GOLD = (201, 163, 92)
DIM = (150, 170, 160)
_SERIF = Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf")
_SANS = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
_IMG_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


@dataclass
class CollageResult:
    ok: bool
    path: str | None
    before_count: int = 0
    after_count: int = 0
    miss: str | None = None
    title: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_before_after_collage(
    root: str | Path,
    *,
    title: str = "Pond Clean-Out",
    max_per_side: int = 4,
    pick_before: str | None = None,
    pick_after: str | None = None,
    dest: Path | None = None,
) -> CollageResult:
    from PIL import Image, ImageDraw, ImageFont, ImageOps

    root = Path(root)
    before = _pick(_collect(root, "before"), pick_before)[: max(1, int(max_per_side))]
    after = _pick(_collect(root, "after"), pick_after)[: max(1, int(max_per_side))]
    if not before and not after:
        return CollageResult(ok=False, path=None, miss="no_images", title=title)

    canvas = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(canvas)
    f_brand = _font(_SANS, 21)
    f_title = _font(_SERIF, 44)
    f_label = _font(_SANS, 30)

    _tracked(d, (W / 2, 42), "CAROLINA WATER GARDENS", f_brand, GOLD, 8)
    d.text((W / 2, 88), title, font=f_title, fill=CREAM, anchor="mm")

    top = 130
    label_h = 56
    bottom = H - 36
    col_w = (W - 12) // 2
    halves: list[tuple[str, list[Path], int, int]] = [
        ("BEFORE", before, 0, col_w),
        ("AFTER", after, W - col_w, col_w),
    ]
    if not (before and after):
        imgs = before or after
        halves = [("", imgs, 0, W)]

    d.rectangle([0, top, W, top + label_h], fill=(9, 27, 23))
    photo_top = top + label_h + 8
    for name, files, x0, cw in halves:
        if name:
            _tracked(
                d,
                (x0 + cw / 2, top + label_h / 2 + 1),
                name,
                f_label,
                GOLD if name == "AFTER" else DIM,
                10,
            )
        if not files:
            d.text(
                (x0 + cw / 2, (photo_top + bottom) / 2),
                "—",
                font=f_title,
                fill=DIM,
                anchor="mm",
            )
            continue
        n = len(files)
        gap = 6
        ch = (bottom - photo_top - (n - 1) * gap) / n
        y = photo_top
        for f in files:
            canvas.paste(_fit(f, cw, int(ch)), (x0, int(y)))
            y += ch + gap
    d.rectangle([W // 2 - 1, top + label_h, W // 2, bottom], fill=BG)

    if dest is None:
        dest = (
            root
            / "collages"
            / datetime.now().strftime("clean-out-%Y%m%d-%H%M%S.png")
        )
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dest, "PNG")
    return CollageResult(
        ok=True,
        path=str(dest.resolve()),
        before_count=len(before),
        after_count=len(after),
        title=title,
    )


def _collect(root: Path, kind: str) -> list[Path]:
    files: list[Path] = []
    seen: set[str] = set()
    needle = kind.lower()
    if not root.is_dir():
        return []
    for d in sorted(root.iterdir()):
        if not d.is_dir() or needle not in d.name.lower():
            continue
        for f in sorted(d.iterdir()):
            if not f.is_file() or f.suffix.lower() not in _IMG_SUFFIXES:
                continue
            digest = md5(f.read_bytes()).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            files.append(f)
    return files


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


def _fit(path: Path, w: int, h: int):
    from PIL import Image, ImageOps

    im = Image.open(path)
    im = ImageOps.exif_transpose(im).convert("RGB")
    return ImageOps.fit(im, (w, h), Image.Resampling.LANCZOS)


def _font(path: Path, size: int):
    from PIL import ImageFont

    if path.is_file():
        return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _tracked(dr, xy, text, font, fill, tracking, anchor="mm") -> None:
    if not tracking:
        dr.text(xy, text, font=font, fill=fill, anchor=anchor)
        return
    widths = [dr.textbbox((0, 0), c, font=font)[2] for c in text]
    total = sum(widths) + tracking * (len(text) - 1)
    x = xy[0] - total / 2
    for c, w in zip(text, widths):
        dr.text((x, xy[1]), c, font=font, fill=fill, anchor="lm")
        x += w + tracking
