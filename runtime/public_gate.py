"""Public auth gate for SOVERYN mobile access.

A tiny auth reverse-proxy that sits in FRONT of the vNext app and is the ONLY
thing exposed to the public internet (via Tailscale Funnel). It forwards
authenticated requests to 127.0.0.1:5001 and streams responses (chat is SSE).

Why a separate gate instead of auth inside the app: internal fleet components
(heartbeat, Vett patrol, specialists, inter-agent comms) call 127.0.0.1:5001
directly with no credential. Putting auth on the app itself would 401 them and
silently break the fleet. This gate leaves :5001 untouched for localhost and
password-protects only the public door.

Credentials come from env: SOVERYN_GATE_USER / SOVERYN_GATE_PASS.
Listens on 127.0.0.1:SOVERYN_GATE_PORT (default 5099); Tailscale Funnel proxies to it.

Remember-me: after one successful Basic login, a signed HttpOnly cookie
(soveryn_gate) keeps the phone signed in for 30 days (sliding refresh). Safari
should stop re-prompting on every Messages open.
"""
import hashlib
import hmac
import os
import sys
import time
from pathlib import Path

import requests
from flask import Flask, Response, request, stream_with_context

# House access log (CF real IP / country) — shared with TGTHRmess + PondWright proxy.
sys.path.insert(0, str(Path.home() / "access-logs"))
try:
    import house_accesslog
except ImportError:
    house_accesslog = None  # type: ignore

UPSTREAM = os.environ.get("SOVERYN_GATE_UPSTREAM", "http://127.0.0.1:5001")
USER = os.environ.get("SOVERYN_GATE_USER", "")
PASS = os.environ.get("SOVERYN_GATE_PASS", "")
PORT = int(os.environ.get("SOVERYN_GATE_PORT", "5099"))

COOKIE_NAME = "soveryn_gate"
COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 days

app = Flask("soveryn-gate")

# Hop-by-hop headers that must not be forwarded (RFC 7230).
_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
        "te", "trailers", "transfer-encoding", "upgrade", "content-encoding",
        "content-length", "host"}


def _cookie_secret() -> bytes:
    return hashlib.sha256(f"{USER}:{PASS}:soveryn-gate-v1".encode()).digest()


def _mint_cookie() -> str:
    exp = int(time.time()) + COOKIE_MAX_AGE
    payload = f"{USER}:{exp}"
    sig = hmac.new(_cookie_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{sig}"


def _cookie_ok() -> bool:
    raw = request.cookies.get(COOKIE_NAME) or ""
    parts = raw.split(":")
    if len(parts) != 3:
        return False
    user, exp_s, sig = parts
    try:
        exp = int(exp_s)
    except ValueError:
        return False
    if exp < int(time.time()):
        return False
    if not hmac.compare_digest(user, USER):
        return False
    expect = hmac.new(
        _cookie_secret(), f"{user}:{exp}".encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(sig, expect)


def _basic_ok() -> bool:
    a = request.authorization
    if not a or not USER or not PASS:
        return False
    return (
        hmac.compare_digest(a.username or "", USER)
        and hmac.compare_digest(a.password or "", PASS)
    )


def _authorized() -> bool:
    return _cookie_ok() or _basic_ok()


def _self_authed_path(path: str) -> bool:
    """The /m/* messenger surface authenticates itself — device bearer secret
    (threads/messages/send), single-use pairing codes (/m/pair/<code>), and a
    localhost-only mint (/m/pair). Its `Authorization: Bearer <secret>` collides
    with THIS gate's HTTP Basic auth (one Authorization header, two claimants),
    so a phone can never satisfy both — threads 401 and the PWA loops on sign-in.
    Let /m/* through the gate untouched; the app enforces its own auth. Everything
    else still requires the gate password."""
    return path == "m" or path.startswith("m/")


def _who() -> str:
    if _self_authed_path(request.path.lstrip("/")):
        return "messenger"
    if _cookie_ok():
        return f"cookie:{USER}"
    a = request.authorization
    if a and a.username:
        return f"basic:{a.username}"
    return "-"


def _attach_remember_cookie(resp: Response) -> Response:
    """Sliding 30-day remember-me so Funnel stops nagging every open."""
    resp.set_cookie(
        COOKIE_NAME,
        _mint_cookie(),
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=True,  # Funnel is HTTPS
        samesite="Lax",
        path="/",
    )
    return resp


if house_accesslog is not None:
    house_accesslog.install_flask(app, site="soveryn-gate", who_fn=_who)


@app.route("/", defaults={"path": ""},
           methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
@app.route("/<path:path>",
           methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
def proxy(path):
    if not _self_authed_path(path) and not _authorized():
        return Response(
            "Authentication required.", 401,
            {"WWW-Authenticate": 'Basic realm="SOVERYN"'},
        )

    url = f"{UPSTREAM}/{path}"
    fwd_headers = {k: v for k, v in request.headers if k.lower() not in _HOP}
    # Real client for the app (Funnel / CF / plain).
    if house_accesslog is not None:
        ip = house_accesslog.client_ip(request.headers, request.remote_addr)
    else:
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "")
    fwd_headers["X-Forwarded-For"] = ip
    fwd_headers["X-Real-IP"] = ip
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        fwd_headers["CF-Connecting-IP"] = cf_ip
    cf_cc = request.headers.get("CF-IPCountry")
    if cf_cc:
        fwd_headers["CF-IPCountry"] = cf_cc

    upstream = requests.request(
        method=request.method,
        url=url,
        params=request.args,
        data=request.get_data(),
        headers=fwd_headers,
        cookies=request.cookies,
        stream=True,           # stream so SSE / chat_stream works
        allow_redirects=False,
        timeout=600,
    )

    resp_headers = [(k, v) for k, v in upstream.raw.headers.items()
                    if k.lower() not in _HOP]

    resp = Response(
        stream_with_context(upstream.iter_content(chunk_size=8192)),
        status=upstream.status_code,
        headers=resp_headers,
    )
    # Refresh remember-me on every successful authed request (Basic or cookie).
    if not _self_authed_path(path):
        _attach_remember_cookie(resp)
    return resp


if __name__ == "__main__":
    if not USER or not PASS:
        raise SystemExit("refusing to start: set SOVERYN_GATE_USER and SOVERYN_GATE_PASS")
    # threaded so streaming one request doesn't block others
    app.run(host="127.0.0.1", port=PORT, threaded=True)
