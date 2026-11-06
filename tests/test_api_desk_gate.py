"""/api/desk-gate end to end on a bare Flask app (revamp phase 1). Nothing is executed."""
import pytest
from flask import Flask


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SOVERYN_DESK_GATE_DB", str(tmp_path / "g.db"))
    from soveryn.app.routes import api_desk_gate
    app = Flask(__name__, template_folder="../soveryn/app/templates")
    app.register_blueprint(api_desk_gate.bp)
    c = app.test_client()
    c.environ_base["REMOTE_ADDR"] = "127.0.0.1"
    return c, api_desk_gate


def _tok(mod):
    from soveryn.kernel_desk import gate
    return {"X-Desk-Gate-Token": gate.GATE_TOKEN}


def test_safe_allowed(client):
    c, mod = client
    r = c.post("/api/desk-gate/check", json={"tool": "bash", "args": {"command": "ls"}}, headers=_tok(mod))
    assert r.get_json()["action"] == "allow"


def test_hold_until_approved_once(client):
    c, mod = client
    r = c.post("/api/desk-gate/check", json={"tool": "bash", "args": {"command": "git push origin fake"}}, headers=_tok(mod))
    assert r.status_code == 202
    gid = r.get_json()["id"]
    assert c.get(f"/api/desk-gate/status/{gid}", headers=_tok(mod)).get_json()["status"] == "pending"
    # decide without CSRF refused
    assert c.post(f"/api/desk-gate/decide/{gid}", json={"decision": "approved"}).status_code == 403
    csrf = c.get("/api/desk-gate/list").get_json()["csrf"]
    assert c.post(f"/api/desk-gate/decide/{gid}", json={"decision": "approved"}, headers={"X-Desk-Gate-CSRF": csrf}).status_code == 200
    first = c.get(f"/api/desk-gate/status/{gid}", headers=_tok(mod)).get_json()
    second = c.get(f"/api/desk-gate/status/{gid}", headers=_tok(mod)).get_json()
    assert first == {"id": gid, "status": "approved", "consumed": False}
    assert second["consumed"] is True  # approval runs once


def test_deny(client):
    c, mod = client
    gid = c.post("/api/desk-gate/check", json={"tool": "bash", "args": {"command": "rm -rf x"}}, headers=_tok(mod)).get_json()["id"]
    csrf = c.get("/api/desk-gate/list").get_json()["csrf"]
    c.post(f"/api/desk-gate/decide/{gid}", json={"decision": "denied"}, headers={"X-Desk-Gate-CSRF": csrf})
    assert c.get(f"/api/desk-gate/status/{gid}", headers=_tok(mod)).get_json()["status"] == "denied"


def test_token_and_funnel_refused(client):
    c, mod = client
    assert c.post("/api/desk-gate/check", json={}).status_code == 403
    from soveryn.edge import EDGE_HEADER, EDGE_PUBLIC
    assert c.get("/api/desk-gate/list", headers={EDGE_HEADER: EDGE_PUBLIC}).status_code == 403
