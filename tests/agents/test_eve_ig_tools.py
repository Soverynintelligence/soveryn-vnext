"""eve_ig_post tool — Gate-facing Instagram desk."""
from __future__ import annotations

from pathlib import Path

from soveryn.agents.eve_ig_tools import build_eve_ig_post_tool
from soveryn.platform.social.instagram_desk import InstagramDesk


class _Sess:
    def __init__(self, logged_in: bool):
        self.logged_in = logged_in

    def check_logged_in(self) -> bool:
        return self.logged_in

    def publish(self, image: Path, caption: str) -> dict:
        return {"ok": True, "status": "posted"}


def test_tool_needs_login(tmp_path: Path):
    img = tmp_path / "p.jpg"
    img.write_bytes(b"\xff\xd8\xff")
    spec = build_eve_ig_post_tool(
        desk=InstagramDesk(session=_Sess(False), media_root=tmp_path)
    )
    out = spec.handler({"brand": "cwg", "caption": "Hello pond.", "image_path": str(img)})
    assert out["status"] == "needs_login"
    assert out["ok"] is False


def test_tool_posts_when_session_warm(tmp_path: Path):
    img = tmp_path / "p.jpg"
    img.write_bytes(b"\xff\xd8\xff")
    spec = build_eve_ig_post_tool(
        desk=InstagramDesk(session=_Sess(True), media_root=tmp_path)
    )
    out = spec.handler({"brand": "cwg", "caption": "Hello pond.", "image_path": str(img)})
    assert out["ok"] is True
    assert out["status"] == "posted"


def test_tool_rejects_non_cwg_brand(tmp_path: Path):
    img = tmp_path / "p.jpg"
    img.write_bytes(b"\xff\xd8\xff")
    spec = build_eve_ig_post_tool(
        desk=InstagramDesk(session=_Sess(True), media_root=tmp_path)
    )
    from soveryn.platform.tools.registry import ToolArgError
    import pytest
    with pytest.raises(ToolArgError):
        spec.handler({"brand": "soveryn", "caption": "House post.", "image_path": str(img)})
