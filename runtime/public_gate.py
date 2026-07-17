"""Public auth gate for SOVERYN mobile access.

A tiny HTTP Basic Auth reverse-proxy that sits in FRONT of the vNext app and is
the ONLY thing exposed to the public internet (via Tailscale Funnel). It forwards
authenticated requests to 127.0.0.1:5001 and streams responses (chat is SSE).

Why a separate gate instead of auth inside the app: internal fleet components
(heartbeat, Vett patrol, specialists, inter-agent comms) call 127.0.0.1:5001
directly with no credential. Putting auth on the app itself would 401 them and
silently break the fleet. This gate leaves :5001 untouched for localhost and
password-protects only the public door.

Credentials come from env: SOVERYN_GATE_USER / SOVERYN_GATE_PASS.
Listens on 127.0.0.1:SOVERYN_GATE_PORT (default 5099); Tailscale Funnel proxies to it.
"""
import os
import hmac

import requests
from flask import Flask, request, Response, stream_with_context

UPSTREAM = os.environ.get("SOVERYN_GATE_UPSTREAM", "http://127.0.0.1:5001")
USER = os.environ.get("SOVERYN_GATE_USER", "")
PASS = os.environ.get("SOVERYN_GATE_PASS", "")
PORT = int(os.environ.get("SOVERYN_GATE_PORT", "5099"))

app = Flask("soveryn-gate")

# Hop-by-hop headers that must not be forwarded (RFC 7230).
_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
        "te", "trailers", "transfer-encoding", "upgrade", "content-encoding",
        "content-length", "host"}


def _authorized() -> bool:
    a = request.authorization
    if not a or not USER or not PASS:
        return False
    # constant-time compare on both fields
    return (hmac.compare_digest(a.username or "", USER)
            and hmac.compare_digest(a.password or "", PASS))


def _self_authed_path(path: str) -> bool:
    """The /m/* messenger surface authenticates itself — device bearer secret
    (threads/messages/send), single-use pairing codes (/m/pair/<code>), and a
    localhost-only mint (/m/pair). Its `Authorization: Bearer <secret>` collides
    with THIS gate's HTTP Basic auth (one Authorization header, two claimants),
    so a phone can never satisfy both — threads 401 and the PWA loops on sign-in.
    Let /m/* through the gate untouched; the app enforces its own auth. Everything
    else still requires the gate password."""
    return path == "m" or path.startswith("m/")


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
    # let the app see the real client + that it's proxied
    fwd_headers["X-Forwarded-For"] = request.headers.get(
        "X-Forwarded-For", request.remote_addr or "")

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

    return Response(
        stream_with_context(upstream.iter_content(chunk_size=8192)),
        status=upstream.status_code,
        headers=resp_headers,
    )


if __name__ == "__main__":
    if not USER or not PASS:
        raise SystemExit("refusing to start: set SOVERYN_GATE_USER and SOVERYN_GATE_PASS")
    # threaded so streaming one request doesn't block others
    app.run(host="127.0.0.1", port=PORT, threaded=True)
