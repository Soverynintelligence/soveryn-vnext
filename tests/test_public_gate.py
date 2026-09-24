"""The public gate must not hand the pairing mint to the open internet."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest


def _load():
    path = Path(__file__).resolve().parents[1] / "runtime" / "public_gate.py"
    spec = importlib.util.spec_from_file_location("public_gate_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def gate():
    mod = _load()
    mod.USER = "jon"
    mod.PASS = "test-pass"
    return mod


def test_pair_mint_is_not_self_authed(gate):
    assert gate._self_authed_path("m/pair") is False
    assert gate._self_authed_path("m/pair/") is False
    assert gate._self_authed_path("m/pair/ABCD-EFGH-1234") is True
    assert gate._self_authed_path("m/threads") is True
    assert gate._self_authed_path("m") is True


def test_unauthed_pair_mint_is_not_forwarded(gate):
    client = gate.app.test_client()
    with patch.object(gate.requests, "request") as upstream:
        resp = client.get("/m/pair", headers={"Accept": "application/json"})
    assert resp.status_code == 401
    upstream.assert_not_called()


def test_phone_browser_gets_a_sign_in_page_instead_of_a_bare_401(gate):
    client = gate.app.test_client()
    with patch.object(gate.requests, "request") as upstream:
        resp = client.get("/", headers={"Accept": "text/html"})
    assert resp.status_code == 302
    assert resp.headers["Location"].startswith("/gate-login")
    upstream.assert_not_called()
    page = client.get("/gate-login")
    assert page.status_code == 200
    assert b'type="password"' in page.data
    bad = client.post("/gate-login", data={"username": "jon", "password": "nope", "next": "/messages"})
    assert bad.status_code == 401
    assert "soveryn_gate" not in bad.headers.getlist("Set-Cookie")
    good = client.post("/gate-login", data={"username": "jon", "password": "test-pass", "next": "/messages"})
    assert good.status_code == 302
    assert good.headers["Location"] == "/messages"
    assert any(c.startswith("soveryn_gate=") for c in good.headers.getlist("Set-Cookie"))


def test_login_next_cannot_leave_the_site(gate):
    assert gate._safe_next("https://evil.example") == "/messages"
    assert gate._safe_next("//evil.example") == "/messages"
    assert gate._safe_next("/messages/eve") == "/messages/eve"


def test_pair_claim_is_forwarded_with_edge_mark(gate):
    client = gate.app.test_client()

    class _Upstream:
        status_code = 200
        raw = type("Raw", (), {"headers": {"Content-Type": "application/json"}})()

        def iter_content(self, chunk_size=8192):
            yield b"{}"

    with patch.object(gate.requests, "request", return_value=_Upstream()) as upstream:
        resp = client.post(
            "/m/pair/ABCD-EFGH-1234",
            headers={"X-Soveryn-Edge": "local", "Authorization": "Bearer phone"},
        )
    assert resp.status_code == 200
    headers = upstream.call_args.kwargs["headers"]
    assert headers["X-Soveryn-Edge"] == "public"
    assert "local" not in headers.values()
    assert headers["Authorization"] == "Bearer phone"
