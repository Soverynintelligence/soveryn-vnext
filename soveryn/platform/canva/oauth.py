"""Canva Connect OAuth 2.0 + PKCE — authorize once, refresh forever."""
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

from soveryn.platform.canva.config import (
    AUTHORIZE_URL,
    TOKEN_URL,
    CanvaConfig,
    load_config,
)

logger = logging.getLogger("soveryn.platform.canva.oauth")


class CanvaAuthError(RuntimeError):
    pass


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def make_pkce() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(64))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def make_state() -> str:
    return _b64url(secrets.token_bytes(32))


def _basic_auth(client_id: str, client_secret: str) -> str:
    raw = f"{client_id}:{client_secret}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


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


def exchange_code(
    config: CanvaConfig,
    *,
    code: str,
    code_verifier: str,
) -> dict[str, Any]:
    body = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": code_verifier,
            "redirect_uri": config.redirect_uri,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        TOKEN_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": _basic_auth(config.client_id, config.client_secret),
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", "replace")[:500]
        raise CanvaAuthError(f"token exchange HTTP {e.code}: {err}") from e
    if "access_token" not in payload:
        raise CanvaAuthError(f"token response missing access_token: {payload}")
    _save_tokens(config.token_path, payload)
    return payload


def refresh_access_token(config: CanvaConfig) -> dict[str, Any]:
    tokens = load_tokens(config.token_path)
    if not tokens or not tokens.get("refresh_token"):
        raise CanvaAuthError(
            "no refresh token — run: python -m soveryn.platform.canva authorize"
        )
    body = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        TOKEN_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": _basic_auth(config.client_id, config.client_secret),
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", "replace")[:500]
        raise CanvaAuthError(f"refresh HTTP {e.code}: {err}") from e
    # Canva rotates refresh tokens — keep old if absent.
    if "refresh_token" not in payload and tokens.get("refresh_token"):
        payload["refresh_token"] = tokens["refresh_token"]
    if "access_token" not in payload:
        raise CanvaAuthError(f"refresh missing access_token: {payload}")
    _save_tokens(config.token_path, payload)
    return payload


def get_access_token(config: CanvaConfig | None = None) -> str:
    cfg = config or load_config()
    if not cfg.configured:
        raise CanvaAuthError(
            "set SOVERYN_CANVA_CLIENT_ID and SOVERYN_CANVA_CLIENT_SECRET"
        )
    tokens = load_tokens(cfg.token_path)
    if not tokens or not tokens.get("access_token"):
        raise CanvaAuthError(
            "not authorized — run: python -m soveryn.platform.canva authorize"
        )
    if float(tokens.get("expires_at") or 0) > time.time():
        return str(tokens["access_token"])
    refreshed = refresh_access_token(cfg)
    return str(refreshed["access_token"])


def build_authorize_url(
    config: CanvaConfig,
    *,
    code_challenge: str,
    state: str,
) -> str:
    q = urllib.parse.urlencode(
        {
            "code_challenge": code_challenge,
            # RFC 7636 + Canva docs: S256. (Some Canva URL examples use s256;
            # uppercase is the mandated method name.)
            "code_challenge_method": "S256",
            "scope": " ".join(config.scopes),
            "response_type": "code",
            "client_id": config.client_id,
            "state": state,
            "redirect_uri": config.redirect_uri,
        }
    )
    return f"{AUTHORIZE_URL}?{q}"


def run_authorize_flow(
    config: CanvaConfig | None = None,
    *,
    open_browser: bool = True,
    timeout_seconds: float = 300.0,
) -> Path:
    """PKCE authorize via local callback. Returns token path."""
    cfg = config or load_config()
    if not cfg.configured:
        raise CanvaAuthError(
            "set SOVERYN_CANVA_CLIENT_ID and SOVERYN_CANVA_CLIENT_SECRET first"
        )

    parsed = urlparse(cfg.redirect_uri)
    if parsed.hostname not in ("127.0.0.1", "localhost"):
        raise CanvaAuthError(
            "CLI authorize expects redirect on 127.0.0.1 — "
            f"got {cfg.redirect_uri!r}"
        )
    port = parsed.port or 8765
    path = parsed.path or "/oauth/canva/callback"

    verifier, challenge = make_pkce()
    state = make_state()
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
                b"<html><body><h1>SOVERYN Canva connected</h1>"
                b"<p>You can close this tab.</p></body></html>"
            )

        def log_message(self, fmt: str, *args: Any) -> None:
            logger.debug("oauth callback: " + fmt, *args)

    server = HTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()

    url = build_authorize_url(cfg, code_challenge=challenge, state=state)
    print("Open this URL to authorize Canva (SOVERYN):")
    print(url)
    if open_browser:
        webbrowser.open(url)

    thread.join(timeout=timeout_seconds)
    server.server_close()
    if error_box:
        raise CanvaAuthError(error_box[0])
    if "code" not in result:
        raise CanvaAuthError("timed out waiting for OAuth callback")
    exchange_code(cfg, code=result["code"], code_verifier=verifier)
    print(f"Tokens saved to {cfg.token_path}")
    return cfg.token_path
