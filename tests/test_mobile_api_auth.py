"""The mobile API must be unreachable without a paired device secret.

`/m/*` is deliberately outside the basic-auth reverse proxy — `public_gate`
lets it through untouched on the promise that the app enforces its own auth.
That promise is the only thing standing between the fleet API and the open
internet, so it is tested rather than assumed.

Every one of these should fail loudly if someone later "simplifies" the
decorator away.
"""
from __future__ import annotations

import pytest
from flask import Flask

from soveryn.app.messenger.auth import AuthError
from soveryn.app.routes import mobile_api


class _FakeStore:
    """Stands in for MessengerStore; only verify_device_secret touches it."""


class _Device:
    device_id = "dev-1"
    label = "phone"


@pytest.fixture()
def app(monkeypatch):
    def fake_verify(store, *, secret):
        if secret == "good-secret":
            return _Device()
        raise AuthError("unknown or revoked device")

    monkeypatch.setattr(mobile_api, "verify_device_secret", fake_verify)

    application = Flask(__name__)
    application.config["TESTING"] = True
    mobile_api.register_mobile_api(
        application,
        messenger_store=_FakeStore(),
        providers={"system/gpu": lambda: {"gpus": ["fake"]}},
    )
    return application


@pytest.fixture()
def client(app):
    return app.test_client()


def test_no_header_is_rejected(client):
    r = client.get("/m/api/system/gpu")
    assert r.status_code == 401
    assert b"fake" not in r.data, "data leaked in an unauthenticated response"


def test_non_bearer_scheme_is_rejected(client):
    r = client.get("/m/api/system/gpu", headers={"Authorization": "Basic abc123"})
    assert r.status_code == 401


def test_wrong_secret_is_rejected(client):
    r = client.get("/m/api/system/gpu",
                   headers={"Authorization": "Bearer not-the-secret"})
    assert r.status_code == 401
    assert b"fake" not in r.data


def test_valid_device_gets_data(client):
    r = client.get("/m/api/system/gpu",
                   headers={"Authorization": "Bearer good-secret"})
    assert r.status_code == 200
    assert r.get_json() == {"gpus": ["fake"]}


def test_whoami_identifies_the_paired_device(client):
    r = client.get("/m/api/whoami",
                   headers={"Authorization": "Bearer good-secret"})
    assert r.status_code == 200
    assert r.get_json()["device_id"] == "dev-1"


def test_whoami_requires_auth_too(client):
    """The liveness probe must not be an unauthenticated existence oracle."""
    assert client.get("/m/api/whoami").status_code == 401


def test_provider_exception_does_not_leak_internals(app, client):
    """A failing provider returns 503, not a stack trace with paths in it."""
    def boom():
        raise RuntimeError("secret path /home/jon-deoliveira/private.db")

    mobile_api.register_mobile_api(
        app, messenger_store=_FakeStore(), providers={"boom": boom},
    )
    r = client.get("/m/api/boom", headers={"Authorization": "Bearer good-secret"})
    assert r.status_code == 503
    assert b"jon-deoliveira" not in r.data
    assert b"RuntimeError" not in r.data


def test_get_providers_reject_mutations(client):
    """GET providers stay GET-only; a phone must not invent write paths."""
    for method in ("post", "put", "delete", "patch"):
        r = getattr(client, method)(
            "/m/api/system/gpu",
            headers={"Authorization": "Bearer good-secret"},
        )
        assert r.status_code == 405, f"{method.upper()} should not be allowed"


def test_post_providers_require_auth(app, client):
    """Ops POSTs are allowed only for paired devices."""
    mobile_api.register_mobile_api(
        app,
        messenger_store=_FakeStore(),
        providers={},
        post_providers={"ops/brain": lambda body: {"ok": True, "brain": body.get("brain")}},
    )
    r = client.post("/m/api/ops/brain", json={"brain": "lightning"})
    assert r.status_code == 401


def test_post_providers_accept_paired_device(app, client):
    """Paired phone can hit the deliberate ops POST allowlist."""
    mobile_api.register_mobile_api(
        app,
        messenger_store=_FakeStore(),
        providers={},
        post_providers={"ops/brain": lambda body: {"ok": True, "brain": body.get("brain")}},
    )
    r = client.post(
        "/m/api/ops/brain",
        headers={"Authorization": "Bearer good-secret"},
        json={"brain": "lightning"},
    )
    assert r.status_code == 200
    assert r.get_json() == {"ok": True, "brain": "lightning"}


def test_post_provider_can_return_status_tuple(app, client):
    mobile_api.register_mobile_api(
        app,
        messenger_store=_FakeStore(),
        providers={},
        post_providers={"ops/tests": lambda body: ({"error": "busy"}, 409)},
    )
    r = client.post(
        "/m/api/ops/tests",
        headers={"Authorization": "Bearer good-secret"},
        json={"suite": "smoke"},
    )
    assert r.status_code == 409
    assert r.get_json()["error"] == "busy"
