"""Eve's Instagram desk — session cookies, no password, media jail."""
from __future__ import annotations

from pathlib import Path

import pytest

from soveryn.platform.social.instagram_desk import (
    ALLOWED_HOSTS,
    InstagramDesk,
    classify_ig_page,
    validate_ig_image,
)


class FakeSession:
    def __init__(self, *, logged_in: bool = False, fail: str | None = None):
        self.logged_in = logged_in
        self.fail = fail
        self.published: list[tuple[str, str]] = []
        self.urls: list[str] = []

    def check_logged_in(self) -> bool:
        return self.logged_in

    def publish(self, image: Path, caption: str) -> dict:
        if not self.logged_in:
            return {"ok": False, "status": "needs_login"}
        if self.fail:
            return {"ok": False, "status": "error", "message": self.fail}
        self.published.append((str(image), caption))
        return {"ok": True, "status": "posted"}


def test_publish_without_session_needs_login(tmp_path: Path):
    img = tmp_path / "pond.jpg"
    img.write_bytes(b"\xff\xd8\xff")  # tiny jpeg-ish
    desk = InstagramDesk(session=FakeSession(logged_in=False), media_root=tmp_path)
    result = desk.publish(image_path=str(img), caption="Clear water.")
    assert result["ok"] is False
    assert result["status"] == "needs_login"
    assert "password" not in result.get("message", "").lower()


def test_publish_when_logged_in_posts_caption_and_image(tmp_path: Path):
    img = tmp_path / "pond.jpg"
    img.write_bytes(b"\xff\xd8\xff")
    session = FakeSession(logged_in=True)
    desk = InstagramDesk(session=session, media_root=tmp_path)
    result = desk.publish(image_path=str(img), caption="Koi in the shade.")
    assert result["ok"] is True
    assert result["status"] == "posted"
    assert session.published == [(str(img.resolve()), "Koi in the shade.")]


def test_image_outside_media_root_is_rejected(tmp_path: Path):
    media = tmp_path / "media"
    media.mkdir()
    outside = tmp_path / "secret.jpg"
    outside.write_bytes(b"\xff\xd8\xff")
    err, path = validate_ig_image(str(outside), media_root=media)
    assert path is None
    assert err
    assert "media" in err.lower() or "inbox" in err.lower()


def test_image_in_desktop_inbox_is_allowed(tmp_path: Path):
    media = tmp_path / "media"
    media.mkdir()
    inbox = tmp_path / "CWG-Instagram"
    inbox.mkdir()
    pic = inbox / "koi.jpg"
    pic.write_bytes(b"\xff\xd8\xff")
    err, path = validate_ig_image(
        str(pic), media_root=media, extra_roots=(inbox,)
    )
    assert err is None
    assert path == pic.resolve()


def test_list_inbox_includes_nested_folders(tmp_path: Path):
    from soveryn.platform.social.instagram_desk import list_inbox_images

    inbox = tmp_path / "CWG-Instagram"
    nested = inbox / "new clean out before "
    nested.mkdir(parents=True)
    pic = nested / "IMG_6061.jpeg"
    pic.write_bytes(b"\xff\xd8\xff")
    listed = list_inbox_images(inbox)
    assert str(pic.resolve()) in listed


def test_empty_caption_rejected(tmp_path: Path):
    img = tmp_path / "pond.jpg"
    img.write_bytes(b"\xff\xd8\xff")
    desk = InstagramDesk(session=FakeSession(logged_in=True), media_root=tmp_path)
    result = desk.publish(image_path=str(img), caption="   ")
    assert result["ok"] is False
    assert result["status"] == "invalid"


def test_caption_over_instagram_limit_rejected(tmp_path: Path):
    img = tmp_path / "pond.jpg"
    img.write_bytes(b"\xff\xd8\xff")
    desk = InstagramDesk(session=FakeSession(logged_in=True), media_root=tmp_path)
    result = desk.publish(image_path=str(img), caption="x" * 2201)
    assert result["ok"] is False
    assert result["status"] == "invalid"


def test_blank_instagram_homepage_is_not_logged_in():
    assert classify_ig_page(url="https://www.instagram.com/") == "unknown"
    assert classify_ig_page(url="https://www.instagram.com/", has_password=True) == "login"
    assert classify_ig_page(url="https://www.instagram.com/accounts/login/") == "login"
    assert classify_ig_page(url="https://www.instagram.com/", has_home=True) == "home"
    assert classify_ig_page(url="https://www.instagram.com/", has_new_post=True) == "home"


def test_allowed_hosts_are_instagram_only():
    assert ALLOWED_HOSTS == frozenset({"instagram.com", "www.instagram.com"})


def test_desk_has_no_password_parameter():
    import inspect
    from soveryn.platform.social.instagram_desk import InstagramDesk as Desk

    sig = inspect.signature(Desk.publish)
    assert "password" not in sig.parameters
    assert "username" not in sig.parameters
    assert "login" not in sig.parameters
