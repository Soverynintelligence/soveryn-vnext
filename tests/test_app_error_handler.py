"""Tests for the global exception handler in soveryn.app.startup.

Ensures uncaught exceptions are logged with a correlation id and (when
the localhost guard is on) the traceback is included in the response
body so debugging the next 500 doesn't require log grepping.
"""

from __future__ import annotations

import json
import logging

import pytest
from flask import Blueprint

from soveryn.agents.loop import AgentLoop
from soveryn.app.startup import create_app
from soveryn.config.runtime import ACTIVE_AGENTS
from soveryn.inference.llama_server_client import ChatResponse
from soveryn.memory.conversation_store import ConversationStore


@pytest.fixture
def fake_chat():
    return lambda req, server, timeout=60: ChatResponse(
        content="ok", finish_reason="stop", tool_calls=None,
        usage=None, raw={})


@pytest.fixture
def app_with_boom(tmp_path, fake_chat):
    """A test app that has an extra route which raises ValueError so we
    can probe the global exception handler end-to-end."""
    conv = ConversationStore(tmp_path / "conv.db")
    loops = {n: AgentLoop(n, conv, chat_fn=fake_chat) for n in ACTIVE_AGENTS}
    app = create_app(conv_store=conv, agent_loops=loops)
    boom_bp = Blueprint("boom", __name__)

    @boom_bp.get("/_test/raise_value_error")
    def _raise_value_error():
        raise ValueError("intentional test failure with context")

    @boom_bp.get("/_test/raise_key_error")
    def _raise_key_error():
        d = {}
        return d["missing_key"]  # noqa

    app.register_blueprint(boom_bp)
    return app


def test_handler_returns_500_with_correlation_id_and_class(app_with_boom):
    """Uncaught ValueError → 500 with correlation_id + exception_class fields."""
    app_with_boom.config["SOVERYN_REQUIRE_LOCALHOST"] = False
    client = app_with_boom.test_client()
    resp = client.get("/_test/raise_value_error")
    assert resp.status_code == 500
    data = resp.get_json()
    assert data["error"]["code"] == "internal_error"
    assert data["error"]["exception_class"] == "ValueError"
    assert isinstance(data["error"]["correlation_id"], str)
    assert len(data["error"]["correlation_id"]) == 12


def test_handler_includes_traceback_when_localhost_guard_on(app_with_boom):
    """SOVERYN_REQUIRE_LOCALHOST=True → traceback in response body."""
    app_with_boom.config["SOVERYN_REQUIRE_LOCALHOST"] = True
    # The localhost guard is also enforced via before_request, so allow
    # the test client through with REMOTE_ADDR=127.0.0.1
    client = app_with_boom.test_client()
    resp = client.get(
        "/_test/raise_value_error",
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert resp.status_code == 500
    data = resp.get_json()
    assert "traceback" in data["error"]
    assert "ValueError" in data["error"]["traceback"]
    assert "intentional test failure" in data["error"]["traceback"]
    assert data["error"]["exception_message"] == "intentional test failure with context"


def test_handler_redacts_traceback_when_localhost_guard_off(app_with_boom):
    """SOVERYN_REQUIRE_LOCALHOST=False → no traceback in body (no internal leak
    when SOVERYN serves remote callers)."""
    app_with_boom.config["SOVERYN_REQUIRE_LOCALHOST"] = False
    client = app_with_boom.test_client()
    resp = client.get("/_test/raise_value_error")
    data = resp.get_json()
    assert "traceback" not in data["error"]
    assert "exception_message" not in data["error"]


def test_handler_logs_correlation_id_with_request_path(app_with_boom, caplog):
    """The log line correlates with the response correlation_id so an
    operator can grep the log for the id from the response body."""
    app_with_boom.config["SOVERYN_REQUIRE_LOCALHOST"] = False
    client = app_with_boom.test_client()
    with caplog.at_level(logging.ERROR, logger="soveryn.app.startup"):
        resp = client.get("/_test/raise_key_error")
        cid = resp.get_json()["error"]["correlation_id"]
    log_messages = " ".join(r.message for r in caplog.records)
    assert cid in log_messages
    assert "/_test/raise_key_error" in log_messages
    assert "KeyError" in log_messages


def test_handler_handles_runaway_traceback_size(app_with_boom):
    """If the traceback explodes (e.g., recursion error), the body is
    capped so the response stays sane."""
    boom_bp = Blueprint("boom_recursion", __name__)

    @boom_bp.get("/_test/recursive_boom")
    def _recursive_boom():
        def f(n):
            return f(n + 1)
        f(0)

    app_with_boom.register_blueprint(boom_bp)
    app_with_boom.config["SOVERYN_REQUIRE_LOCALHOST"] = True
    client = app_with_boom.test_client()
    resp = client.get(
        "/_test/recursive_boom",
        environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert resp.status_code == 500
    data = resp.get_json()
    # Traceback present but capped
    assert "traceback" in data["error"]
    assert len(data["error"]["traceback"]) <= 8050  # cap + "[truncated]" suffix
    assert "RecursionError" in data["error"]["exception_class"]


def test_handler_defers_to_http_exception_status(app_with_boom):
    """If a Werkzeug HTTPException slips through (e.g., abort(418)), the
    handler should keep its status code, not wrap it as a 500."""
    from werkzeug.exceptions import abort
    teapot_bp = Blueprint("teapot", __name__)

    @teapot_bp.get("/_test/teapot")
    def _teapot():
        abort(418)

    app_with_boom.register_blueprint(teapot_bp)
    app_with_boom.config["SOVERYN_REQUIRE_LOCALHOST"] = False
    client = app_with_boom.test_client()
    resp = client.get("/_test/teapot")
    assert resp.status_code == 418
    data = resp.get_json()
    assert data["error"]["code"].startswith("http_")


def test_handler_returns_clean_404_via_existing_handler(app_with_boom):
    """Regression: the 404 handler still fires its specific path; the
    catch-all doesn't shadow it."""
    app_with_boom.config["SOVERYN_REQUIRE_LOCALHOST"] = False
    client = app_with_boom.test_client()
    resp = client.get("/_test/does_not_exist")
    assert resp.status_code == 404
    assert resp.get_json()["error"]["code"] == "not_found"
