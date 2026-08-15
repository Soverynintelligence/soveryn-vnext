"""Device-authed API surface for the mobile app, mounted under /m/api/.

## Why this exists rather than reusing /api/ directly

Mission Control's 21 JSON endpoints live under `/api/` and are protected by the
basic-auth reverse proxy (`runtime/public_gate.py`). The mobile app cannot use
basic auth: iOS runs a Home Screen PWA in its own storage context, credentials
do not reliably persist, and being re-prompted on every launch is precisely what
makes a web page feel like a web page instead of an app.

The messenger already solved this — `/m/*` carries a paired-device bearer secret
and the gate lets it through untouched because the app enforces its own auth
(`public_gate._self_authed_path`). Mounting the app's API under `/m/api/`
inherits that for free:

  - no change to public_gate, so nothing new is exposed by configuration
  - `/api/` keeps its existing basic-auth protection for the desktop UI
  - every call here requires a paired, revocable device secret

The alternative — widening the gate's bypass list to cover `/api/` — would put
the entire fleet API on the public internet behind nothing. Not done, and should
not be done later as a shortcut.

## What it does NOT do

No new data, no new queries. Each route delegates to the same service functions
the desktop routes call, so there is exactly one implementation of each read and
this surface cannot drift into a second source of truth.

Mostly read-only. A short allowlist of POSTs (`ops/brain`, `ops/tests`) is wired
so Mission Control on a paired phone can switch the Spark brain and run test
suites without basic auth — same ops_control service as desktop, device bearer
as the gate. Other mutating endpoints (`/api/specialists/kill`, X approvals,
delegation dispatch) stay absent: a phone in a pocket is a different threat
model, and consequential actions should stay where confirmation is deliberate.
Revisit per-endpoint, never by opening the prefix wholesale.
"""
from __future__ import annotations

import logging
from functools import wraps

from flask import Blueprint, jsonify, request

from soveryn.app.messenger.auth import AuthError, verify_device_secret

logger = logging.getLogger(__name__)


def _require_device(messenger_store):
    """Bearer-token gate. Mirrors routes/messenger.py so there is one auth model.

    Kept as a local decorator rather than imported so this module has no import
    cycle with the messenger blueprint; the verification itself is shared.
    """
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            header = request.headers.get("Authorization", "")
            if not header.startswith("Bearer "):
                return jsonify({"error": "missing bearer token"}), 401
            try:
                device = verify_device_secret(messenger_store,
                                              secret=header[len("Bearer "):])
            except AuthError as exc:
                return jsonify({"error": str(exc)}), 401
            request.authed_device = device
            return fn(*args, **kwargs)
        return wrapper
    return deco


def register_mobile_api(
    app,
    *,
    messenger_store,
    providers: dict[str, callable],
    post_providers: dict[str, callable] | None = None,
):
    """Mount /m/api/<name> for each provider, all behind device auth.

    providers maps a route name to a zero-arg callable returning JSON-able data.
    post_providers maps a route name to a callable(body: dict) -> JSON-able
    for deliberate mutations (brain switch, test runs). Device auth is the
    gate — paired phone is trusted the same way localhost is on desktop ops.
    """
    # Built per call, not at module scope: a module-level Blueprint cannot be
    # registered twice and silently couples every app instance in a test run to
    # the same mutable object. Flask raises on the second add_url_rule, which is
    # how this was caught.
    bp_name = f"mobile_api_{len(app.blueprints)}"
    bp = Blueprint(bp_name, __name__, url_prefix="/m/api")
    require = _require_device(messenger_store)
    post_providers = post_providers or {}

    def _make(name: str, fn):
        @require
        def view():
            try:
                return jsonify(fn())
            except Exception:
                # Never leak internals to a device on the public internet.
                logger.exception("mobile api %s failed", name)
                return jsonify({"error": "unavailable"}), 503
        view.__name__ = f"mobile_{name.replace('/', '_').replace('-', '_')}"
        return view

    def _make_post(name: str, fn):
        @require
        def view():
            try:
                body = request.get_json(silent=True) or {}
                result = fn(body if isinstance(body, dict) else {})
                # Allow callables to return (payload, status) for 4xx.
                if isinstance(result, tuple) and len(result) == 2:
                    payload, status = result
                    return jsonify(payload), status
                return jsonify(result)
            except Exception:
                logger.exception("mobile api POST %s failed", name)
                return jsonify({"error": "unavailable"}), 503
        view.__name__ = f"mobile_post_{name.replace('/', '_').replace('-', '_')}"
        return view

    for name, fn in providers.items():
        bp.add_url_rule(f"/{name}", view_func=_make(name, fn), methods=["GET"])

    for name, fn in post_providers.items():
        bp.add_url_rule(
            f"/{name}",
            view_func=_make_post(name, fn),
            methods=["POST"],
            endpoint=f"mobile_post_{name.replace('/', '_')}",
        )

    @bp.get("/whoami", endpoint="whoami")
    @require
    def whoami():
        """Cheap liveness + auth check the app can call on launch.

        Lets the client distinguish "not paired yet" (401) from "paired but the
        server is unreachable" (network error) — which is the difference between
        showing a pairing screen and showing an offline banner.
        """
        d = request.authed_device
        return jsonify({
            "device_id": getattr(d, "device_id", None),
            "label": getattr(d, "label", None),
            "ok": True,
        })

    app.register_blueprint(bp)
    logger.info(
        "mobile api mounted at /m/api with %d GET + %d POST providers",
        len(providers), len(post_providers),
    )
    return bp
