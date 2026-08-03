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

Read-only by design. Mutating endpoints the desktop exposes (`/api/specialists/kill`,
X approvals, delegation dispatch) are deliberately absent: a phone in a pocket is
a different threat model from a desktop behind basic auth on a LAN, and consequential
actions should stay where confirmation is deliberate. Revisit per-endpoint, never
by opening the prefix wholesale.
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


def register_mobile_api(app, *, messenger_store, providers: dict[str, callable]):
    """Mount /m/api/<name> for each provider, all behind device auth.

    providers maps a route name to a zero-arg callable returning JSON-able data.
    Passing the callables in keeps this module free of service imports, so the
    app decides what the phone can see and that decision lives in one place.
    """
    # Built per call, not at module scope: a module-level Blueprint cannot be
    # registered twice and silently couples every app instance in a test run to
    # the same mutable object. Flask raises on the second add_url_rule, which is
    # how this was caught.
    bp_name = f"mobile_api_{len(app.blueprints)}"
    bp = Blueprint(bp_name, __name__, url_prefix="/m/api")
    require = _require_device(messenger_store)

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

    for name, fn in providers.items():
        bp.add_url_rule(f"/{name}", view_func=_make(name, fn), methods=["GET"])

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
    logger.info("mobile api mounted at /m/api with %d providers", len(providers))
    return bp
