"""Google OAuth 2.0 + PKCE for Business Profile — authorize once, refresh forever."""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from soveryn.platform.gbp.config import (
    AUTHORIZE_URL,
    SCOPE,
    TOKEN_URL,
    GbpConfig,
    load_config,
)

logger = logging.getLogger("soveryn.platform.gbp.oauth")


class GbpAuthError(RuntimeError):
    pass


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def make_pkce() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(64))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def _save_tokens(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    expires_in = int(payload.get("expires_in") or 0)
    record = {
        "access_token": payload["access_token"],
        "refresh_token": payload.get("refresh_token"),
        "token_type": payload.get("token_type", "Bearer"),
        "expires_at": now + max(expires_in - 60, 0),
        "scope": payload.get("scope"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def load_tokens(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _token_post(body: dict[str, str]) -> dict[str, Any]:
    req = urllib.request.Request(
        TOKEN_URL,
        data=urllib.parse.urlencode(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", "replace")[:500]
        raise GbpAuthError(f"token HTTP {e.code}: {err}") from e


def exchange_code(config: GbpConfig, *, code: str, code_verifier: str) -> dict[str, Any]:
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
        raise GbpAuthError(f"token response missing access_token: {payload}")
    _save_tokens(config.token_path, payload)
    return payload


def refresh_access_token(config: GbpConfig) -> dict[str, Any]:
    tokens = load_tokens(config.token_path)
    if not tokens or not tokens.get("refresh_token"):
        raise GbpAuthError(
            "no refresh token — run: python -m soveryn.platform.gbp authorize"
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
        raise GbpAuthError(f"refresh missing access_token: {payload}")
    _save_tokens(config.token_path, payload)
    return payload


def get_access_token(config: GbpConfig | None = None) -> str:
    cfg = config or load_config()
    if not cfg.configured:
        raise GbpAuthError(
            "set SOVERYN_GBP_CLIENT_ID and SOVERYN_GBP_CLIENT_SECRET"
        )
    tokens = load_tokens(cfg.token_path)
    if not tokens or not tokens.get("access_token"):
        raise GbpAuthError(
            "not authorized — run: python -m soveryn.platform.gbp authorize"
        )
    if float(tokens.get("expires_at") or 0) > time.time():
        return str(tokens["access_token"])
    return str(refresh_access_token(cfg)["access_token"])


def build_authorize_url(
    config: GbpConfig, *, code_challenge: str, state: str
) -> str:
    q = urllib.parse.urlencode(
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
    config: GbpConfig | None = None,
    *,
    open_browser: bool = True,
    timeout_seconds: float = 300.0,
) -> Path:
    cfg = config or load_config()
    if not cfg.configured:
        raise GbpAuthError(
            "set SOVERYN_GBP_CLIENT_ID and SOVERYN_GBP_CLIENT_SECRET first"
        )
    parsed = urlparse(cfg.redirect_uri)
    if parsed.hostname not in ("127.0.0.1", "localhost"):
        raise GbpAuthError(
            f"CLI authorize expects redirect on 127.0.0.1 — got {cfg.redirect_uri!r}"
        )
    port = parsed.port or 8766
    path = parsed.path or "/oauth/gbp/callback"
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
            qs = urllib.parse.parse_qs(u.query)
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
                b"<html><body><h1>SOVERYN Google Business connected</h1>"
                b"<p>You can close this tab.</p></body></html>"
            )

        def log_message(self, fmt: str, *args: Any) -> None:
            logger.debug("oauth callback: " + fmt, *args)

    server = HTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    url = build_authorize_url(cfg, code_challenge=challenge, state=state)
    print("Open this URL to authorize Google Business Profile (CWG):")
    print(url)
    if open_browser:
        webbrowser.open(url)
    thread.join(timeout=timeout_seconds)
    server.server_close()
    if error_box:
        raise GbpAuthError(error_box[0])
    if "code" not in result:
        raise GbpAuthError("timed out waiting for OAuth callback")
    exchange_code(cfg, code=result["code"], code_verifier=verifier)
    print(f"Tokens saved to {cfg.token_path}")
    return cfg.token_path
