"""Per-agent browser desks — persistent Chrome profiles Jon signs into.

Eve does not type passwords. You log in once (headed Chrome + 2FA). The
session cookies live under data/desks/<agent>/<seat>/chrome (gitignored).

Eve's Google seat is the CWG Google account: Business Profile and Ads.
She may *use* that login. She must not create campaigns or change budget
from a tool until a later gated spend path exists.
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
DESKS_ROOT = _PROJECT_ROOT / "data" / "desks"

AGENTS = ("aetheria", "kernel", "eve")


@dataclass(frozen=True)
class Seat:
    agent: str
    seat: str
    label: str
    start_url: str


SEATS: tuple[Seat, ...] = (
    Seat(
        "eve",
        "google",
        "Eve · CWG Google (Business + Ads)",
        "https://ads.google.com/aw/overview",
    ),
    Seat(
        "eve",
        "instagram",
        "Eve · CWG Instagram",
        "https://www.instagram.com/",
    ),
    Seat(
        "aetheria",
        "browser",
        "Aetheria · browser",
        "https://accounts.google.com/",
    ),
    Seat(
        "kernel",
        "browser",
        "Kernel · browser",
        "https://accounts.google.com/",
    ),
)


def seat_for(agent: str, seat: str) -> Seat:
    agent = (agent or "").strip().lower()
    seat = (seat or "").strip().lower()
    for s in SEATS:
        if s.agent == agent and s.seat == seat:
            return s
    raise ValueError(
        f"unknown desk {agent}/{seat}. "
        f"Known: {', '.join(f'{x.agent}/{x.seat}' for x in SEATS)}"
    )


def profile_dir(agent: str, seat: str) -> Path:
    spec = seat_for(agent, seat)
    if spec.agent == "eve" and spec.seat == "instagram":
        # Keep the live Instagram cookies where they already are.
        return _PROJECT_ROOT / "data" / "eve_ig_profile"
    return DESKS_ROOT / spec.agent / spec.seat / "chrome"


def classify_google_page(*, url: str, has_password: bool = False) -> str:
    """login | home | unknown for Google Ads / Business / accounts."""
    u = (url or "").lower()
    if has_password:
        return "login"
    if "accounts.google.com" in u and (
        "/signin" in u or "/servicelogin" in u or "/v3/signin" in u
    ):
        return "login"
    if "ads.google.com" in u and "/aw/" in u:
        return "home"
    if "business.google.com" in u and "signin" not in u:
        return "home"
    if "myaccount.google.com" in u:
        return "home"
    return "unknown"


def _launch_kwargs(profile: Path, *, headed: bool) -> dict:
    import os

    display = os.environ.get("DISPLAY") or ":1"
    env = {**os.environ, "DISPLAY": display}
    profile.mkdir(parents=True, exist_ok=True)
    return {
        "user_data_dir": str(profile),
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


def _signed_in_from_profile(path: Path) -> dict[str, Any]:
    """Read Chrome Preferences / cookies without launching a second browser.

    Needed when the headed login window still holds SingletonLock.
    """
    import json
    import sqlite3

    prefs_path = path / "Default" / "Preferences"
    cookies_path = path / "Default" / "Cookies"
    email = None
    if prefs_path.is_file():
        try:
            prefs = json.loads(prefs_path.read_text(encoding="utf-8"))
            services = (prefs.get("google") or {}).get("services") or {}
            email = services.get("last_signed_in_username")
            if not email:
                info = prefs.get("account_info") or []
                if isinstance(info, list) and info:
                    email = (info[0] or {}).get("email")
        except (OSError, json.JSONDecodeError, TypeError):
            email = None
    auth_cookies = False
    if cookies_path.is_file():
        try:
            conn = sqlite3.connect(
                f"file:{cookies_path.resolve()}?mode=ro", uri=True, timeout=1
            )
            row = conn.execute(
                "SELECT 1 FROM cookies WHERE name IN ('SID','SAPISID','__Secure-1PSID') "
                "AND host_key LIKE '%google.com' LIMIT 1"
            ).fetchone()
            conn.close()
            auth_cookies = row is not None
        except sqlite3.Error:
            auth_cookies = False
    return {"email": email, "auth_cookies": auth_cookies}


def desk_status(agent: str, seat: str) -> dict[str, Any]:
    spec = seat_for(agent, seat)
    path = profile_dir(agent, seat)
    empty = (not path.exists()) or (path.exists() and not any(path.iterdir()))
    if spec.seat == "instagram":
        return {
            "ok": True,
            "agent": spec.agent,
            "seat": spec.seat,
            "label": spec.label,
            "logged_in": None,
            "status": "instagram_desk",
            "profile": str(path),
            "message": (
                "Instagram uses the dedicated IG desk. "
                "`python -m soveryn.platform.social.instagram_desk login`"
            ),
        }
    if empty:
        return {
            "ok": True,
            "agent": spec.agent,
            "seat": spec.seat,
            "label": spec.label,
            "logged_in": False,
            "status": "needs_login",
            "profile": str(path),
            "message": (
                f"No session yet. Jon: "
                f"`python -m soveryn.platform.social.agent_desk login "
                f"{spec.agent} {spec.seat}`"
            ),
        }
    hint = _signed_in_from_profile(path)
    try:
        logged_in = _probe_logged_in(spec, path)
    except Exception as e:
        # Profile in use by the headed login window — don't lie "not logged in".
        if hint.get("email") or hint.get("auth_cookies"):
            return {
                "ok": True,
                "agent": spec.agent,
                "seat": spec.seat,
                "label": spec.label,
                "logged_in": True,
                "status": "ready",
                "profile": str(path),
                "account": hint.get("email"),
                "message": (
                    f"Signed in as {hint.get('email') or 'Google account'} "
                    "(Chrome desk still open)."
                ),
            }
        return {
            "ok": False,
            "agent": spec.agent,
            "seat": spec.seat,
            "logged_in": False,
            "status": "error",
            "profile": str(path),
            "message": str(e),
        }
    return {
        "ok": True,
        "agent": spec.agent,
        "seat": spec.seat,
        "label": spec.label,
        "logged_in": logged_in,
        "status": "ready" if logged_in else "needs_login",
        "profile": str(path),
        "account": hint.get("email") if logged_in else None,
        "message": (
            f"Signed in as {hint.get('email')}."
            if logged_in and hint.get("email")
            else (
                None
                if logged_in
                else (
                    f"Session cold. Jon: "
                    f"`python -m soveryn.platform.social.agent_desk login "
                    f"{spec.agent} {spec.seat}`"
                )
            )
        ),
    }


def _probe_logged_in(spec: Seat, path: Path) -> bool:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            **_launch_kwargs(path, headed=False)
        )
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(spec.start_url, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(2000)
            has_pw = page.locator('input[type="password"]').count() > 0
            return classify_google_page(url=page.url, has_password=has_pw) == "home"
        finally:
            ctx.close()


def login_interactive(agent: str, seat: str, *, timeout_s: float = 600.0) -> int:
    """Open headed Chrome on this agent's desk. Eve never types the password."""
    import os

    from playwright.sync_api import sync_playwright

    spec = seat_for(agent, seat)
    path = profile_dir(agent, seat)
    path.mkdir(parents=True, exist_ok=True)
    display = os.environ.get("DISPLAY") or ":1"
    print(f"{spec.label}")
    print(f"Profile: {path}")
    print(f"Display: {display}")
    print("A Chrome window should appear. Sign in as that desk's Google/IG account.")
    print("Complete 2FA. When you see the logged-in home, come back here and press Enter.")
    print("Eve does not type credentials.")
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            **_launch_kwargs(path, headed=True)
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.bring_to_front()
        except Exception:
            pass
        page.goto(spec.start_url, wait_until="domcontentloaded")
        if sys.stdin.isatty():
            try:
                input("Press Enter when the account is signed in… ")
            except EOFError:
                pass
        else:
            print("No TTY — waiting up to 10 minutes for a logged-in URL…")
            deadline = time.time() + timeout_s
            while time.time() < deadline:
                has_pw = page.locator('input[type="password"]').count() > 0
                if classify_google_page(url=page.url, has_password=has_pw) == "home":
                    break
                time.sleep(2)
        has_pw = page.locator('input[type="password"]').count() > 0
        state = classify_google_page(url=page.url, has_password=has_pw)
        ctx.close()
    if state == "home":
        print("Desk is signed in.")
        return 0
    print(f"Not sure this is logged in (page={state}). Re-run login if the window looked wrong.")
    return 1


def list_desks() -> list[dict[str, Any]]:
    out = []
    for spec in SEATS:
        path = profile_dir(spec.agent, spec.seat)
        out.append(
            {
                "agent": spec.agent,
                "seat": spec.seat,
                "label": spec.label,
                "profile": str(path),
                "has_profile": path.exists() and any(path.glob("*")),
            }
        )
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m soveryn.platform.social.agent_desk",
        description="Per-agent browser desks. Jon signs in; agents use the session.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="Show desks and whether a profile exists")
    st = sub.add_parser("status", help="Probe whether the desk is signed in")
    st.add_argument("agent")
    st.add_argument("seat")
    lg = sub.add_parser("login", help="Open headed Chrome so Jon can sign in")
    lg.add_argument("agent")
    lg.add_argument("seat")
    args = p.parse_args(argv)
    if args.cmd == "list":
        for row in list_desks():
            mark = "profile" if row["has_profile"] else "empty"
            print(f"{row['agent']}/{row['seat']:10} {mark:8} {row['label']}")
        return 0
    if args.cmd == "status":
        info = desk_status(args.agent, args.seat)
        print(info.get("status"), info.get("message") or info.get("label"))
        return 0 if info.get("logged_in") else 2
    if args.cmd == "login":
        return login_interactive(args.agent, args.seat)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
