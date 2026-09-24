"""Eve desk tools: make_canvas, draw_rect, draw_text (print-card path)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PIL")

from soveryn.platform.intake.tools import (
    build_compose_image_tool,
    build_decode_qr_tool,
    build_draw_rect_tool,
    build_draw_text_tool,
    build_make_canvas_tool,
    build_make_qr_tool,
)
from soveryn.platform.tools.registry import ToolArgError


PAYLOAD = "https://soveryn.example/print-card"
NAVY = "#071A2C"
NAVY_RGB = (7, 26, 44)


def _canvas(tmp_path: Path):
    return build_make_canvas_tool(owner_agent="eve", media_root=tmp_path)


def _rect(tmp_path: Path):
    return build_draw_rect_tool(
        owner_agent="eve",
        allowed_roots=(tmp_path,),
        media_root=tmp_path,
    )


def _text(tmp_path: Path):
    return build_draw_text_tool(
        owner_agent="eve",
        allowed_roots=(tmp_path,),
        media_root=tmp_path,
    )


def _qr(tmp_path: Path):
    return build_make_qr_tool(owner_agent="eve", media_root=tmp_path)


def _compose(tmp_path: Path):
    return build_compose_image_tool(
        owner_agent="eve",
        allowed_roots=(tmp_path,),
        media_root=tmp_path,
    )


def _decode(tmp_path: Path):
    return build_decode_qr_tool(owner_agent="eve", allowed_roots=(tmp_path,))


def test_make_canvas_writes_png_of_requested_size(tmp_path):
    from PIL import Image

    result = _canvas(tmp_path).handler({
        "width": 80,
        "height": 50,
        "fill": NAVY,
        "name": "field",
    })
    assert result["ok"] is True
    assert result["miss"] is None
    assert result["width"] == 80
    assert result["height"] == 50
    dest = Path(result["path"])
    assert dest.is_file()
    assert dest.suffix == ".png"
    assert dest.parent.name == "canvas"
    assert dest.resolve().is_relative_to(tmp_path.resolve())
    img = Image.open(dest)
    assert img.size == (80, 50)
    assert img.getpixel((0, 0)) == NAVY_RGB


def test_make_canvas_short_hex(tmp_path):
    from PIL import Image

    result = _canvas(tmp_path).handler({
        "width": 4,
        "height": 4,
        "fill": "#0F0",
    })
    assert result["ok"] is True
    assert Image.open(result["path"]).getpixel((0, 0)) == (0, 255, 0)


@pytest.mark.parametrize(
    "width,height,fill",
    [
        (0, 100, NAVY),
        (-1, 100, NAVY),
        (4097, 100, NAVY),
        (100, 0, NAVY),
        (100, -8, NAVY),
        (100, 4097, NAVY),
        (80, 50, "navy"),
        (80, 50, "rgb(7,26,44)"),
        (80, 50, "071A2C"),
    ],
)
def test_make_canvas_rejects_bad_edges_and_fill(tmp_path, width, height, fill):
    with pytest.raises(ToolArgError):
        _canvas(tmp_path).handler({
            "width": width,
            "height": height,
            "fill": fill,
        })


def test_draw_rect_writes_new_path(tmp_path):
    made = _canvas(tmp_path).handler({
        "width": 200, "height": 120, "fill": NAVY,
    })
    src = Path(made["path"])
    before = src.read_bytes()
    result = _rect(tmp_path).handler({
        "path": str(src),
        "x": 10,
        "y": 10,
        "width": 80,
        "height": 60,
        "fill": "#FFFFFF",
        "outline": "#C9A227",
        "stroke": 2,
        "radius": 8,
    })
    assert result["ok"] is True, result
    assert result["miss"] is None
    out = Path(result["path"])
    assert out.is_file()
    assert out.resolve() != src.resolve()
    assert out.parent.name == "composed"
    assert src.read_bytes() == before
    assert result["width"] == 200
    assert result["height"] == 120


def test_draw_rect_overhang_is_clipped_not_refused(tmp_path):
    made = _canvas(tmp_path).handler({
        "width": 40, "height": 40, "fill": "#000000",
    })
    result = _rect(tmp_path).handler({
        "path": made["path"],
        "x": 30,
        "y": 30,
        "width": 20,
        "height": 20,
        "fill": "#FFFFFF",
    })
    assert result["ok"] is True, result
    assert Path(result["path"]).is_file()


def test_draw_rect_fully_outside_is_would_clip(tmp_path):
    made = _canvas(tmp_path).handler({
        "width": 40, "height": 40, "fill": "#000000",
    })
    result = _rect(tmp_path).handler({
        "path": made["path"],
        "x": 80,
        "y": 80,
        "width": 10,
        "height": 10,
        "fill": "#FFFFFF",
    })
    assert result["ok"] is False
    assert result["miss"] == "would_clip"


def test_draw_rect_missing_file_is_explicit_miss(tmp_path):
    missing = tmp_path / "nope.png"
    result = _rect(tmp_path).handler({
        "path": str(missing),
        "x": 0,
        "y": 0,
        "width": 10,
        "height": 10,
        "fill": "#FFFFFF",
    })
    assert result["ok"] is False
    assert result["miss"] == "file_not_found"


def test_draw_rect_requires_fill_or_outline(tmp_path):
    made = _canvas(tmp_path).handler({
        "width": 20, "height": 20, "fill": NAVY,
    })
    with pytest.raises(ToolArgError, match="fill or outline"):
        _rect(tmp_path).handler({
            "path": made["path"],
            "x": 0,
            "y": 0,
            "width": 10,
            "height": 10,
        })


def test_draw_text_writes_new_path_input_untouched(tmp_path):
    made = _canvas(tmp_path).handler({
        "width": 300, "height": 80, "fill": NAVY,
    })
    src = Path(made["path"])
    before = src.read_bytes()
    result = _text(tmp_path).handler({
        "path": str(src),
        "text": "Scan to review",
        "x": 20,
        "y": 16,
        "size": 22,
        "color": "#C9A227",
        "font": "serif",
        "align": "left",
    })
    assert result["ok"] is True, result
    assert result["miss"] is None
    out = Path(result["path"])
    assert out.is_file()
    assert out.resolve() != src.resolve()
    assert out.parent.name == "composed"
    assert src.read_bytes() == before
    assert result["width"] == 300
    assert result["height"] == 80


def test_draw_text_empty_is_arg_error(tmp_path):
    made = _canvas(tmp_path).handler({
        "width": 40, "height": 40, "fill": NAVY,
    })
    with pytest.raises(ToolArgError, match="non-empty"):
        _text(tmp_path).handler({
            "path": made["path"],
            "text": "   ",
            "x": 0,
            "y": 0,
            "size": 12,
            "color": "#FFFFFF",
        })


@pytest.mark.parametrize("builder", [_rect, _text])
def test_draw_path_outside_allowed_roots(tmp_path, builder):
    outside = Path("/etc/hostname")
    if not outside.is_file():
        outside = Path("/etc/passwd")
    args = {
        "path": str(outside),
        "x": 0,
        "y": 0,
    }
    if builder is _rect:
        args.update({"width": 10, "height": 10, "fill": "#FFFFFF"})
    else:
        args.update({"text": "hello", "size": 12, "color": "#FFFFFF"})
    with pytest.raises(ToolArgError, match="outside allowed intake roots"):
        builder(tmp_path).handler(args)


def test_print_card_canvas_plate_qr_compose_decode(tmp_path):
    """Print-card path: canvas → plate → QR → compose → decode."""
    pytest.importorskip("cv2")

    card = _canvas(tmp_path).handler({
        "width": 800,
        "height": 500,
        "fill": NAVY,
        "name": "review-card",
    })
    assert card["ok"] is True
    plated = _rect(tmp_path).handler({
        "path": card["path"],
        "x": 40,
        "y": 40,
        "width": 240,
        "height": 240,
        "fill": "#FFFFFF",
        "radius": 8,
    })
    assert plated["ok"] is True, plated
    made = _qr(tmp_path).handler({"url": PAYLOAD})
    assert made["ok"] is True
    composed = _compose(tmp_path).handler({
        "base": plated["path"],
        "overlay": made["path"],
        "x": 50,
        "y": 50,
        "width": 220,
        "height": 220,
    })
    assert composed["ok"] is True, composed
    out = Path(composed["path"])
    assert out.is_file()
    decoded = _decode(tmp_path).handler({"path": str(out)})
    assert decoded["ok"] is True
    assert PAYLOAD in decoded["payloads"]
