"""Eve CWG before/after collage desk tool."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PIL")

from soveryn.platform.intake.collage import build_before_after_collage
from soveryn.platform.intake.tools import build_look_at_tool, build_make_collage_tool
from soveryn.platform.tools.registry import ToolArgError


def _solid(path: Path, color: tuple[int, int, int]) -> Path:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (200, 200), color).save(path, format="JPEG")
    return path


def _job(tmp_path: Path) -> Path:
    root = tmp_path / "CWG-Instagram"
    _solid(root / "new clean out before" / "b1.jpg", (80, 60, 40))
    _solid(root / "new clean out before" / "b2.jpg", (90, 70, 50))
    _solid(root / "new clean out after" / "a1.jpg", (40, 120, 80))
    _solid(root / "new clean out after" / "a2.jpg", (50, 140, 90))
    return root


def test_collage_writes_ig_portrait_png(tmp_path: Path):
    root = _job(tmp_path)
    result = build_before_after_collage(root, title="Pond Clean-Out")
    assert result.ok is True
    dest = Path(result.path)
    assert dest.is_file()
    assert dest.suffix == ".png"
    assert dest.parent.name == "collages"
    from PIL import Image

    im = Image.open(dest)
    assert im.size == (1080, 1350)
    assert result.before_count == 2
    assert result.after_count == 2


def test_collage_miss_when_no_before_after_folders(tmp_path: Path):
    root = tmp_path / "empty"
    root.mkdir()
    result = build_before_after_collage(root)
    assert result.ok is False
    assert result.miss == "no_images"
    assert result.path is None


def test_make_collage_tool_eve_only_writes_under_root(tmp_path: Path):
    root = _job(tmp_path)
    tool = build_make_collage_tool(
        owner_agent="eve",
        allowed_roots=(tmp_path,),
        default_root=root,
    )
    out = tool.handler({"title": "Pond Clean-Out", "max": 2})
    assert out["ok"] is True
    assert Path(out["path"]).is_file()
    assert out["before_count"] == 2
    assert out["after_count"] == 2


def test_make_collage_tool_rejects_root_outside_allowlist(tmp_path: Path):
    root = _job(tmp_path)
    tool = build_make_collage_tool(
        owner_agent="eve",
        allowed_roots=(tmp_path / "other",),
        default_root=root,
    )
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(ToolArgError, match="outside"):
        tool.handler({"root": str(root)})


def test_look_at_side_before_returns_vision_and_names(tmp_path: Path):
    root = _job(tmp_path)
    tool = build_look_at_tool(
        owner_agent="eve",
        allowed_roots=(tmp_path,),
        default_root=root,
    )
    out = tool.handler({"side": "before", "max": 4})
    assert out["ok"] is True
    assert out["count"] >= 1
    names = [f["name"] for f in out["files"]]
    assert "b1.jpg" in names
    assert "_vision" in out
    assert all(u.startswith("data:image/jpeg;base64,") for u in out["_vision"])
    dumped = str({k: v for k, v in out.items() if k != "_vision"})
    assert "base64" not in dumped


def test_look_at_side_before_finds_folder_with_trailing_space(tmp_path: Path):
    root = tmp_path / "CWG-Instagram"
    spaced = root / "new clean out before "
    _solid(spaced / "IMG_6061.jpeg", (80, 60, 40))
    _solid(root / "new clean out after " / "IMG_6139.jpeg", (40, 120, 80))
    tool = build_look_at_tool(
        owner_agent="eve",
        allowed_roots=(tmp_path,),
        default_root=root,
    )
    out = tool.handler({"side": "before"})
    assert out["ok"] is True
    assert [f["name"] for f in out["files"]] == ["IMG_6061.jpeg"]


def test_look_at_rejects_path_outside_allowlist(tmp_path: Path):
    tool = build_look_at_tool(
        owner_agent="eve",
        allowed_roots=(tmp_path / "cage",),
        default_root=tmp_path / "cage",
    )
    (tmp_path / "cage").mkdir()
    outsider = tmp_path / "secret.jpg"
    _solid(outsider, (1, 2, 3))
    with pytest.raises(ToolArgError, match="outside"):
        tool.handler({"path": str(outsider)})


def test_look_at_pick_orders_and_skips_byte_dupes(tmp_path: Path):
    root = _job(tmp_path)
    before = root / "new clean out before"
    dup = before / "b1-copy.jpg"
    dup.write_bytes((before / "b1.jpg").read_bytes())
    tool = build_look_at_tool(
        owner_agent="eve",
        allowed_roots=(tmp_path,),
        default_root=root,
    )
    all_before = tool.handler({"side": "before", "max": 8})
    assert all_before["count"] == 2
    picked = tool.handler({"side": "before", "pick": "b2,b1.jpg", "max": 4})
    assert [f["name"] for f in picked["files"]] == ["b2.jpg"]
    # b1.jpg was the duplicate of b1-copy (sorted first); pick "b1.jpg"
    # does not match the surviving copy's name.
