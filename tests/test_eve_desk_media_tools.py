"""Eve desk tools: make_qr + compose_image (decode_qr covered separately)."""

from __future__ import annotations

from pathlib import Path

import pytest

cv2 = pytest.importorskip("cv2")
pytest.importorskip("PIL")

from soveryn.platform.intake.qr import decode_qr_bytes
from soveryn.platform.intake.tools import (
    build_compose_image_tool,
    build_decode_qr_tool,
    build_make_qr_tool,
)
from soveryn.platform.tools.registry import ToolArgError


PAYLOAD = "https://soveryn.example/review-card"


def _make_qr(tmp_path: Path):
    return build_make_qr_tool(owner_agent="eve", media_root=tmp_path)


def _compose(tmp_path: Path):
    return build_compose_image_tool(
        owner_agent="eve",
        allowed_roots=(tmp_path,),
        media_root=tmp_path,
    )


def _decode(tmp_path: Path):
    return build_decode_qr_tool(owner_agent="eve", allowed_roots=(tmp_path,))


def _solid_png(path: Path, *, w: int, h: int, color=(20, 40, 60)) -> Path:
    from PIL import Image

    Image.new("RGB", (w, h), color).save(path, format="PNG")
    return path


def test_make_qr_then_decode_qr_recovers_url(tmp_path):
    made = _make_qr(tmp_path).handler({"url": PAYLOAD})
    assert made["ok"] is True
    assert made["miss"] is None
    dest = Path(made["path"])
    assert dest.is_file()
    assert dest.suffix == ".png"
    assert dest.resolve().is_relative_to(tmp_path.resolve())
    decoded = _decode(tmp_path).handler({"path": str(dest)})
    assert decoded["ok"] is True
    assert PAYLOAD in decoded["payloads"]


def test_make_qr_rejects_empty_url(tmp_path):
    with pytest.raises(ToolArgError, match="non-empty"):
        _make_qr(tmp_path).handler({"url": "   "})


@pytest.mark.parametrize(
    "url",
    ["ftp://example.com/x", "file:///etc/passwd", "javascript:alert(1)", "not-a-url"],
)
def test_make_qr_rejects_non_http_url(tmp_path, url):
    with pytest.raises(ToolArgError, match="http/https|hostname"):
        _make_qr(tmp_path).handler({"url": url})


def test_make_qr_does_not_fetch(tmp_path, monkeypatch):
    """Encode-only: a fetch attempt would be a policy break."""
    import urllib.request

    def _boom(*_a, **_k):
        raise AssertionError("make_qr must not fetch the URL")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    made = _make_qr(tmp_path).handler({"url": "https://example.invalid/no-fetch"})
    assert made["ok"] is True
    assert Path(made["path"]).is_file()


def test_compose_image_qr_on_card_then_decode(tmp_path):
    made = _make_qr(tmp_path).handler({"url": PAYLOAD})
    qr_path = Path(made["path"])
    card = _solid_png(tmp_path / "card.png", w=800, h=500)
    result = _compose(tmp_path).handler({
        "base": str(card),
        "overlay": str(qr_path),
        "x": 40,
        "y": 40,
        "width": 220,
        "height": 220,
    })
    assert result["ok"] is True, result
    out = Path(result["path"])
    assert out.is_file()
    assert out.resolve().is_relative_to(tmp_path.resolve())
    decoded = _decode(tmp_path).handler({"path": str(out)})
    assert decoded["ok"] is True
    assert PAYLOAD in decoded["payloads"]
    # Bytes on disk match what decode_qr_bytes sees (print-ready file).
    assert PAYLOAD in decode_qr_bytes(out.read_bytes()).payloads


def test_compose_image_missing_file_is_explicit_miss(tmp_path):
    card = _solid_png(tmp_path / "card.png", w=200, h=200)
    missing = tmp_path / "nope.png"
    result = _compose(tmp_path).handler({
        "base": str(card),
        "overlay": str(missing),
        "x": 0,
        "y": 0,
    })
    assert result["ok"] is False
    assert result["miss"] == "file_not_found"
    assert result["path"] == str(missing.resolve()) or result["path"] == str(missing)


def test_compose_image_clip_refused_unless_flag(tmp_path):
    card = _solid_png(tmp_path / "card.png", w=100, h=100)
    overlay = _solid_png(tmp_path / "ov.png", w=50, h=50, color=(200, 10, 10))
    refused = _compose(tmp_path).handler({
        "base": str(card),
        "overlay": str(overlay),
        "x": 70,
        "y": 70,
    })
    assert refused["ok"] is False
    assert refused["miss"] == "would_clip"

    clipped = _compose(tmp_path).handler({
        "base": str(card),
        "overlay": str(overlay),
        "x": 70,
        "y": 70,
        "clip": True,
    })
    assert clipped["ok"] is True
    assert Path(clipped["path"]).is_file()


def test_compose_image_path_outside_roots(tmp_path):
    outside = Path("/etc/hostname")
    if not outside.is_file():
        outside = Path("/etc/passwd")
    with pytest.raises(ToolArgError, match="outside allowed intake roots"):
        _compose(tmp_path).handler({
            "base": str(outside),
            "overlay": str(outside),
            "x": 0,
            "y": 0,
        })
