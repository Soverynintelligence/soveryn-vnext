"""End-to-end Flask route behaviour for /m/*."""
from __future__ import annotations
import json
import pytest
from flask import Flask

from soveryn.app.routes.messenger import build_messenger_blueprint
from soveryn.app.messenger.store import MessengerStore
from soveryn.memory.conversation_store import ConversationStore


@pytest.fixture
def app(tmp_path):
    flask_app = Flask(__name__)
    messenger_store = MessengerStore(tmp_path / "m.db")
    conv_store = ConversationStore(tmp_path / "conv.db")
    bp = build_messenger_blueprint(
        messenger_store=messenger_store,
        conv_store=conv_store,
        agent_loops={},  # routes don't dispatch chat until Task 9
    )
    flask_app.register_blueprint(bp)
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


def test_pair_admin_route_serves_pairing_page(client):
    resp = client.get("/m/pair", environ_base={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "pairing" in body.lower() or "code" in body.lower()


def test_pair_admin_route_rejects_non_localhost(client):
    resp = client.get("/m/pair", environ_base={"REMOTE_ADDR": "192.168.1.50"})
    assert resp.status_code == 403


def test_pair_claim_with_valid_code(client):
    # First mint a code (via admin POST)
    mint_resp = client.post(
        "/m/pair", json={"label": "phone"},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert mint_resp.status_code == 200
    code = mint_resp.get_json()["code"]
    # Claim it (this is the phone-side request)
    claim_resp = client.post(
        f"/m/pair/{code}", json={"device_label": "Pixel 9"},
    )
    assert claim_resp.status_code == 200
    data = claim_resp.get_json()
    assert "device_id" in data
    assert "secret" in data


def test_threads_endpoint_requires_auth(client):
    resp = client.get("/m/threads")
    assert resp.status_code == 401


def test_threads_endpoint_works_with_bearer(client):
    mint_resp = client.post(
        "/m/pair", json={"label": "phone"},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    code = mint_resp.get_json()["code"]
    claim_resp = client.post(f"/m/pair/{code}", json={"device_label": "Pixel 9"})
    secret = claim_resp.get_json()["secret"]
    resp = client.get(
        "/m/threads",
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert resp.status_code == 200
    assert resp.get_json() == {"threads": []}
