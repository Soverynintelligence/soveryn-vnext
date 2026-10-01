"""CWG Instagram desk — persistent browser profile, no password, one action: post.

Jon logs in once (headed Chrome + 2FA). Eve's tool may only publish a caption +
image under data/media/ after Messages Gate Allow. Cadence must not call this.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any, Protocol

ALLOWED_HOSTS = frozenset({"instagram.com", "www.instagram.com"})
IG_HOME = "https://www.instagram.com/"
CAPTION_LIMIT = 2200


def classify_ig_page(
    *,
    url: str,
    has_password: bool = False,
    has_home: bool = False,
    has_new_post: bool = False,
) -> str:
    """login | home | unknown — never treat a blank IG homepage as logged in."""
    u = (url or "").lower()
    path = u.split("instagram.com", 1)[-1] if "instagram.com" in u else u
    if has_password or "accounts/login" in u or path.startswith("/login") or "/login?" in path or "/login/" in path:
        return "login"
    if has_home or has_new_post:
        return "home"
    return "unknown"
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PROFILE = _PROJECT_ROOT / "data" / "eve_ig_profile"
DEFAULT_MEDIA = _PROJECT_ROOT / "data" / "media"
# Jon drops CWG Instagram photos here (Desktop). Not the whole Desktop.
DEFAULT_INBOX = Path.home() / "Desktop" / "CWG-Instagram"


class InstagramSession(Protocol):
    def check_logged_in(self) -> bool: ...
    def publish(self, image: Path, caption: str) -> dict: ...


def _allowed_roots(media_root: Path, extra_roots: tuple[Path, ...] | None) -> list[Path]:
    roots = [media_root.resolve()]
    for r in extra_roots or ():
        if r.exists():
            roots.append(r.resolve())
    return roots


def _in_roots(p: Path, roots: list[Path]) -> bool:
    for r in roots:
        try:
            p.relative_to(r)
            return True
        except ValueError:
            continue
    return False


def list_inbox_images(inbox: Path | None = None) -> list[str]:
    folder = Path(inbox) if inbox else DEFAULT_INBOX
    if not folder.is_dir():
        return []
    out: list[str] = []
    files = [
        p
        for p in folder.rglob("*")
        if p.is_file() and p.suffix.lower() in _IMAGE_SUFFIXES
    ]
    files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return [str(p.resolve()) for p in files]


def validate_ig_image(
    raw: str,
    *,
    media_root: Path,
    extra_roots: tuple[Path, ...] | None = None,
) -> tuple[str | None, Path | None]:
    """Image must exist under data/media/ or the CWG Instagram desktop inbox."""
    extras = extra_roots if extra_roots is not None else (
        (DEFAULT_INBOX,) if DEFAULT_INBOX.exists() else ()
    )
    roots = _allowed_roots(media_root, extras)
    if not (raw or "").strip():
        return "image_path is required", None
    p = Path(raw.strip())
    if not p.is_absolute():
        candidates = []
        if p.parts and p.parts[0] == "data":
            candidates.append((_PROJECT_ROOT / p).resolve())
        candidates.append((media_root / p).resolve())
        candidates.append((media_root / p.name).resolve())
        for r in extras:
            candidates.append((r / p).resolve())
            candidates.append((r / p.name).resolve())
        p = next((c for c in candidates if c.is_file()), candidates[0])
    else:
        p = p.resolve()
    if not _in_roots(p, roots):
        return (
            "image must be under data/media/ or Desktop/CWG-Instagram",
            None,
        )
    if not p.is_file():
        return f"image not found: {p}", None
    if p.suffix.lower() not in _IMAGE_SUFFIXES:
        return f"unsupported image type {p.suffix}", None
    return None, p


class InstagramDesk:
    def __init__(
        self,
        *,
        session: InstagramSession,
        media_root: Path | None = None,
        inbox: Path | None = None,
    ) -> None:
        self._session = session
        self.media_root = Path(media_root) if media_root else DEFAULT_MEDIA
        self.inbox = Path(inbox) if inbox is not None else DEFAULT_INBOX

    def status(self) -> dict[str, Any]:
        try:
            logged_in = bool(self._session.check_logged_in())
        except Exception as e:
            return {"ok": False, "status": "error", "logged_in": False, "message": str(e)}
        return {
            "ok": True,
            "status": "ready" if logged_in else "needs_login",
            "logged_in": logged_in,
        }

    def publish(self, *, image_path: str, caption: str) -> dict[str, Any]:
        cap = (caption or "").strip()
        if not cap:
            return {"ok": False, "status": "invalid", "message": "caption is empty"}
        if len(cap) > CAPTION_LIMIT:
            return {
                "ok": False,
                "status": "invalid",
                "message": f"caption is {len(cap)} chars — Instagram limit is {CAPTION_LIMIT}",
            }
        extras = (self.inbox,) if self.inbox.exists() else ()
        err, image = validate_ig_image(
            image_path, media_root=self.media_root, extra_roots=extras
        )
        if err or image is None:
            return {"ok": False, "status": "invalid", "message": err or "bad image"}
        try:
            if not self._session.check_logged_in():
                return {
                    "ok": False,
                    "status": "needs_login",
                    "message": (
                        "Instagram session is cold. Jon: run "
                        "`python -m soveryn.platform.social.instagram_desk login` "
                        "and complete 2FA in the window. Eve does not type credentials."
                    ),
                }
            return self._session.publish(image, cap)
        except Exception as e:
            return {"ok": False, "status": "error", "message": str(e)}


class PlaywrightIgSession:
    """Persistent Chrome profile on instagram.com only."""

    def __init__(self, *, profile_dir: Path, headed: bool = False) -> None:
        self.profile_dir = Path(profile_dir)
        self.headed = headed

    def _context(self):
        from playwright.sync_api import sync_playwright

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        pw = sync_playwright().start()
        ctx = pw.chromium.launch_persistent_context(
            **_launch_kwargs(self.profile_dir, headed=self.headed)
        )
        return pw, ctx

    def check_logged_in(self) -> bool:
        pw, ctx = self._context()
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(IG_HOME, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(2500)
            return _page_is_home(page)
        finally:
            ctx.close()
            pw.stop()

    def publish(self, image: Path, caption: str) -> dict:
        pw, ctx = self._context()
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(IG_HOME, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(1200)
            if "accounts/login" in page.url.lower() or page.locator('input[name="password"]').count():
                return {
                    "ok": False,
                    "status": "needs_login",
                    "message": "Session expired. Jon must re-login the desk.",
                }
            # New post
            create = page.get_by_role("link", name="New post").or_(
                page.locator('svg[aria-label="New post"]')
            )
            if create.count() == 0:
                create = page.locator('a[href="#"]').filter(has_text="Create")
            try:
                create.first.click(timeout=8_000)
            except Exception:
                shot = self.profile_dir / "last_error.png"
                page.screenshot(path=str(shot))
                return {
                    "ok": False,
                    "status": "error",
                    "message": f"Could not open New post (IG UI). Screenshot: {shot}",
                }
            page.wait_for_timeout(800)
            file_input = page.locator('input[type="file"]')
            if file_input.count() == 0:
                shot = self.profile_dir / "last_error.png"
                page.screenshot(path=str(shot))
                return {
                    "ok": False,
                    "status": "error",
                    "message": f"No file picker on create. Screenshot: {shot}",
                }
            file_input.first.set_input_files(str(image))
            page.wait_for_timeout(1500)
            for _ in range(2):
                nxt = page.get_by_role("button", name="Next")
                if nxt.count():
                    nxt.first.click()
                    page.wait_for_timeout(800)
            cap_box = page.locator('textarea[aria-label="Write a caption…"]').or_(
                page.locator('div[aria-label="Write a caption…"]')
            )
            if cap_box.count():
                cap_box.first.fill(caption)
            else:
                # contenteditable fallback
                editable = page.locator('[contenteditable="true"]')
                if editable.count():
                    editable.first.fill(caption)
            page.wait_for_timeout(400)
            share = page.get_by_role("button", name="Share")
            if share.count() == 0:
                shot = self.profile_dir / "last_error.png"
                page.screenshot(path=str(shot))
                return {
                    "ok": False,
                    "status": "error",
                    "message": f"Share button not found. Screenshot: {shot}",
                }
            share.first.click()
            page.wait_for_timeout(2500)
            return {"ok": True, "status": "posted", "platform": "instagram"}
        except Exception as e:
            try:
                page = ctx.pages[0]
                page.screenshot(path=str(self.profile_dir / "last_error.png"))
            except Exception:
                pass
            return {"ok": False, "status": "error", "message": str(e)}
        finally:
            ctx.close()
            pw.stop()


def _page_is_home(page) -> bool:
    url = page.url
    has_pw = page.locator('input[name="password"]').count() > 0
    has_home = page.locator('svg[aria-label="Home"]').count() > 0
    has_new = page.locator('svg[aria-label="New post"]').count() > 0
    return classify_ig_page(
        url=url,
        has_password=has_pw,
        has_home=has_home,
        has_new_post=has_new,
    ) == "home"


def _launch_kwargs(profile_dir: Path, *, headed: bool) -> dict:
    import os

    display = os.environ.get("DISPLAY") or ":1"
    env = {**os.environ, "DISPLAY": display}
    return {
        "user_data_dir": str(profile_dir),
        "channel": "chrome",
        "headless": not headed,
        "viewport": {"width": 1280, "height": 900},
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--password-store=basic",
            "--no-first-run",
        ],
        "ignore_default_args": ["--enable-automation"],
        "env": env,
    }


def default_desk(*, headed: bool = False) -> InstagramDesk:
    return InstagramDesk(
        session=PlaywrightIgSession(profile_dir=DEFAULT_PROFILE, headed=headed),
        media_root=DEFAULT_MEDIA,
    )


def login_interactive(timeout_s: float = 600.0) -> int:
    """Open headed Chrome. Do not close until the home feed is really there."""
    import os

    from playwright.sync_api import sync_playwright

    DEFAULT_PROFILE.mkdir(parents=True, exist_ok=True)
    display = os.environ.get("DISPLAY") or ":1"
    print(f"Opening Instagram desk profile:\n  {DEFAULT_PROFILE}")
    print(f"Display: {display}")
    print("A Chrome window should appear on this machine.")
    print("Log in as the CWG Instagram account. Complete 2FA.")
    print("When you see the home feed, come back here and press Enter.")
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            **_launch_kwargs(DEFAULT_PROFILE, headed=True)
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.bring_to_front()
        except Exception:
            pass
        page.goto(IG_HOME, wait_until="domcontentloaded")
        print("If no window appeared, this command is on the wrong display.")
        if sys.stdin.isatty():
            try:
                input("Press Enter when the Instagram home feed is visible… ")
            except EOFError:
                pass
        else:
            print("No TTY — waiting up to 10 minutes for the home feed markers…")
            deadline = time.time() + timeout_s
            while time.time() < deadline and not _page_is_home(page):
                time.sleep(2)
        logged = _page_is_home(page)
        ctx.close()
    if logged:
        print("Session saved. Eve can post after Messages Allow.")
        return 0
    print("Not on the home feed — session NOT saved as logged in. Run login again.")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Eve CWG Instagram desk")
    parser.add_argument("cmd", choices=("login", "status"))
    args = parser.parse_args(argv)
    if args.cmd == "login":
        return login_interactive()
    desk = default_desk(headed=False)
    print(desk.status())
    return 0 if desk.status().get("logged_in") else 2


if __name__ == "__main__":
    sys.exit(main())
