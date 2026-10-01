"""Google OAuth 2.0 + PKCE for Calendar — authorize once, refresh forever."""
from __future__ import annotations

import logging
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from soveryn.platform.gbp.oauth import (
    _b64url,
    _save_tokens,
    _token_post,
    load_tokens,
    make_pkce,
)
from soveryn.platform.gcal.config import (
    AUTHORIZE_URL,
    SCOPE,
    GcalConfig,
    load_config,
)

logger = logging.getLogger("soveryn.platform.gcal.oauth")


class GcalAuthError(RuntimeError):
    pass


def exchange_code(config: GcalConfig, *, code: str, code_verifier: str) -> dict[str, Any]:
    payload = _token_post(
        {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": code_verifier,
            "redirect_uri": config.redirect_uri,
            "client_id": config.client_id,
            "client_secret": config.client_secret,
        }
    )
    if "access_token" not in payload:
        raise GcalAuthError(f"token response missing access_token: {payload}")
    _save_tokens(config.token_path, payload)
    return payload


def refresh_access_token(config: GcalConfig) -> dict[str, Any]:
    tokens = load_tokens(config.token_path)
    if not tokens or not tokens.get("refresh_token"):
        raise GcalAuthError(
            "no refresh token — run: python -m soveryn.platform.gcal authorize"
        )
    payload = _token_post(
        {
            "grant_type": "refresh_token",
            "refresh_token": str(tokens["refresh_token"]),
            "client_id": config.client_id,
            "client_secret": config.client_secret,
        }
    )
    if "refresh_token" not in payload and tokens.get("refresh_token"):
        payload["refresh_token"] = tokens["refresh_token"]
    if "access_token" not in payload:
        raise GcalAuthError(f"refresh missing access_token: {payload}")
    _save_tokens(config.token_path, payload)
    return payload


def get_access_token(config: GcalConfig | None = None) -> str:
    cfg = config or load_config()
    if not cfg.configured:
        raise GcalAuthError(
            "set SOVERYN_GBP_CLIENT_ID / SOVERYN_GBP_CLIENT_SECRET "
            "(or SOVERYN_GCAL_CLIENT_*)"
        )
    tokens = load_tokens(cfg.token_path)
    if not tokens or not tokens.get("access_token"):
        raise GcalAuthError(
            "not authorized — run: python -m soveryn.platform.gcal authorize"
        )
    if float(tokens.get("expires_at") or 0) > time.time():
        return str(tokens["access_token"])
    return str(refresh_access_token(cfg)["access_token"])


def build_authorize_url(
    config: GcalConfig, *, code_challenge: str, state: str
) -> str:
    from urllib.parse import urlencode

    q = urlencode(
        {
            "response_type": "code",
            "client_id": config.client_id,
            "redirect_uri": config.redirect_uri,
            "scope": SCOPE,
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{AUTHORIZE_URL}?{q}"


def run_authorize_flow(
    config: GcalConfig | None = None,
    *,
    open_browser: bool = True,
    timeout_seconds: float = 300.0,
) -> Path:
    cfg = config or load_config()
    if not cfg.configured:
        raise GcalAuthError(
            "set SOVERYN_GBP_CLIENT_ID and SOVERYN_GBP_CLIENT_SECRET first"
        )
    parsed = urlparse(cfg.redirect_uri)
    if parsed.hostname not in ("127.0.0.1", "localhost"):
        raise GcalAuthError(
            f"CLI authorize expects redirect on 127.0.0.1 — got {cfg.redirect_uri!r}"
        )
    port = parsed.port or 8767
    path = parsed.path or "/oauth/gcal/callback"
    verifier, challenge = make_pkce()
    state = _b64url(secrets.token_bytes(32))
    result: dict[str, str] = {}
    error_box: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            u = urlparse(self.path)
            if u.path != path:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"not found")
                return
            from urllib.parse import parse_qs

            qs = parse_qs(u.query)
            if qs.get("state", [None])[0] != state:
                error_box.append("state mismatch")
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"state mismatch")
                return
            if "error" in qs:
                error_box.append(qs["error"][0])
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"authorization denied")
                return
            code = qs.get("code", [None])[0]
            if not code:
                error_box.append("missing code")
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"missing code")
                return
            result["code"] = code
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h1>SOVERYN Google Calendar connected</h1>"
                b"<p>You can close this tab.</p></body></html>"
            )

        def log_message(self, fmt: str, *args: Any) -> None:
            logger.debug("oauth callback: " + fmt, *args)

    server = HTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    url = build_authorize_url(cfg, code_challenge=challenge, state=state)
    print("Open this URL to authorize Google Calendar (CWG):")
    print(url)
    if open_browser:
        webbrowser.open(url)
    thread.join(timeout=timeout_seconds)
    server.server_close()
    if error_box:
        raise GcalAuthError(error_box[0])
    if "code" not in result:
        raise GcalAuthError("timed out waiting for OAuth callback")
    exchange_code(cfg, code=result["code"], code_verifier=verifier)
    print(f"Tokens saved to {cfg.token_path}")
    return cfg.token_path
