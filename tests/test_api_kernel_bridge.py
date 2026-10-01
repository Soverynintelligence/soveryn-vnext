"""Localhost Kernel CLI → Messages bridge."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from soveryn.app.routes import api_kernel_bridge as bridge


@dataclass
class _Sess:
    session_id: str


class _FakeConv:
    def __init__(self):
        self.turns = []
        self._sessions = [_Sess("sess-k")]

    def list_sessions(self, agent=None, limit=1):
        return self._sessions[:limit]

    def new_session(self, agent, title=None):
        return "sess-new"

    def save_turn(self, *args, **kwargs):
        self.turns.append((args, kwargs))

    def _conn(self):
        class _C:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def execute(self_inner, *a, **k):
                return None

        return _C()


@pytest.fixture()
def app(monkeypatch):
    from flask import Flask

    app = Flask(__name__)
    fake = _FakeConv()
    app.extensions["soveryn"] = {"conv_store": fake}
    app.register_blueprint(bridge.bp)
    monkeypatch.setattr(
        "soveryn.platform.webpush.notify.notify_needs_you", lambda **k: None
    )
    return app, fake


def test_kernel_cli_receipt_localhost(app):
    flask_app, fake = app
    client = flask_app.test_client()
    r = client.post(
        "/api/internal/kernel_cli_receipt",
        json={
            "action": "status",
            "body": "READY.",
            "ok": True,
            "run_id": "abc-123",
            "verdict": ["[PASS] kernel status: exit=0"],
            "finish_reason": "stop",
        },
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["agent"] == "kernel"
    assert fake.turns
    args, kwargs = fake.turns[0]
    assert args[1] == "kernel"
    assert args[2] == "assistant"
    assert kwargs["source"] == "kernel_cli"
    assert "abc-123" in args[3]


def test_tool_round_limit_forced_fail(app):
    flask_app, fake = app
    client = flask_app.test_client()
    r = client.post(
        "/api/internal/kernel_cli_receipt",
        json={
            "body": "almost done",
            "ok": True,
            "finish_reason": "tool_round_limit",
        },
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert r.status_code == 200
    assert "tool_round_limit" in r.get_json()["status"]
    bubble = fake.turns[0][0][3]
    assert "not success" in bubble


def test_rejects_non_localhost(app):
    flask_app, _ = app
    client = flask_app.test_client()
    r = client.post(
        "/api/internal/kernel_cli_receipt",
        json={"body": "x"},
        environ_base={"REMOTE_ADDR": "10.0.0.2"},
    )
    assert r.status_code == 403
