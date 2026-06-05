"""Tests for the Signal Direct Line bridge — config, JSON parser,
daemon allowlist + dispatch + outbound retry.

Subprocess and HTTP are mocked throughout. The live signal-cli is
exercised only by interactive verification, not the unit suite.
"""

from __future__ import annotations

import json
import sqlite3
from unittest.mock import patch, MagicMock

import pytest

from soveryn.agents.signal_bridge.client import (
    InboundMessage,
    SignalCliError,
    parse_envelopes,
)
from soveryn.agents.signal_bridge.config import SignalBridgeConfig
from soveryn.agents.signal_bridge.daemon import SignalBridgeDaemon
from soveryn.platform.lattice.legacy import LatticeStore


# ─── Config ──────────────────────────────────────────────────────────────────

def test_config_from_env_parses_allowlist():
    env = {
        "SOVERYN_SIGNAL_BOT_NUMBER": "+19102489392",
        "SOVERYN_SIGNAL_ALLOWED_NUMBERS": "+19105813970,+15555550100",
        "SOVERYN_SIGNAL_CLI_BIN": "/usr/local/bin/signal-cli",
    }
    cfg = SignalBridgeConfig.from_env(env)
    assert cfg.bot_number == "+19102489392"
    assert cfg.allowed_numbers == frozenset({"+19105813970", "+15555550100"})
    assert cfg.signal_cli_bin == "/usr/local/bin/signal-cli"
    assert cfg.enabled is True


def test_config_empty_allowlist_yields_empty_frozenset():
    cfg = SignalBridgeConfig.from_env({"SOVERYN_SIGNAL_BOT_NUMBER": "+1"})
    assert cfg.allowed_numbers == frozenset()


def test_config_disabled_flag():
    cfg = SignalBridgeConfig.from_env({
        "SOVERYN_SIGNAL_BOT_NUMBER": "+1",
        "SOVERYN_SIGNAL_BRIDGE_ENABLED": "false",
    })
    assert cfg.enabled is False


# ─── JSON-LD envelope parser ────────────────────────────────────────────────

def test_parse_envelopes_extracts_text_message():
    raw = json.dumps({
        "envelope": {
            "source": "+19105813970",
            "timestamp": 1779801096748,
            "dataMessage": {"message": "Hi", "attachments": []},
        },
    }) + "\n"
    out = parse_envelopes(raw)
    assert len(out) == 1
    assert out[0].source_e164 == "+19105813970"
    assert out[0].body == "Hi"
    assert out[0].timestamp_ms == 1779801096748
    assert out[0].attachment_paths == ()


def test_parse_envelopes_extracts_attachment_filename():
    raw = json.dumps({
        "envelope": {
            "source": "+19105813970",
            "timestamp": 1,
            "dataMessage": {
                "message": "look at this",
                "attachments": [{"id": "att-123.jpg", "contentType": "image/jpeg"}],
            },
        },
    }) + "\n"
    out = parse_envelopes(raw)
    assert out[0].attachment_paths == ("att-123.jpg",)


def test_parse_envelopes_skips_non_text_envelopes():
    """Read receipts / typing indicators / sync messages don't have
    dataMessage — they should be silently dropped."""
    raw = (
        json.dumps({"envelope": {"source": "+1", "receiptMessage": {}}}) + "\n"
        + json.dumps({"envelope": {"source": "+1", "typingMessage": {}}}) + "\n"
    )
    assert parse_envelopes(raw) == ()


def test_parse_envelopes_tolerates_bad_lines():
    """One malformed line shouldn't kill the batch."""
    raw = (
        "not json at all\n"
        + json.dumps({"envelope": {"source": "+1", "timestamp": 1,
                                    "dataMessage": {"message": "good"}}}) + "\n"
        + "{broken json\n"
    )
    out = parse_envelopes(raw)
    assert len(out) == 1
    assert out[0].body == "good"


# ─── Daemon: allowlist + dispatch ───────────────────────────────────────────

@pytest.fixture
def lattice_db(tmp_path):
    db = tmp_path / "lattice.db"
    LatticeStore(db)
    return db


@pytest.fixture
def conv_db(tmp_path):
    return tmp_path / "conv.db"  # NOT created — daemon hits API


def _config(**kw) -> SignalBridgeConfig:
    base = dict(
        bot_number="+19102489392",
        allowed_numbers=frozenset({"+19105813970"}),
        signal_cli_bin="/usr/local/bin/signal-cli",
        vnext_base="http://127.0.0.1:5001",
        chat_timeout_seconds=240,
        enabled=True,
        poll_interval_seconds=2.0,
        outbound_max_retries=3,
        outbound_initial_backoff_seconds=0.01,
    )
    base.update(kw)
    return SignalBridgeConfig(**base)


def test_daemon_drops_off_allowlist_with_audit(lattice_db, conv_db):
    daemon = SignalBridgeDaemon(_config(), lattice_db=lattice_db, conv_db=conv_db)
    msg = InboundMessage(
        source_e164="+15555550199",  # NOT on allowlist
        timestamp_ms=1,
        body="hello",
        attachment_paths=(),
    )
    daemon._handle_inbound(msg)
    with sqlite3.connect(str(lattice_db)) as con:
        rows = con.execute(
            "SELECT direction, sender_e164, error FROM signal_log"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0] == ("dropped", "+15555550199", "sender not in allowlist")


def test_daemon_routes_allowlisted_message_to_chat(lattice_db, conv_db):
    daemon = SignalBridgeDaemon(_config(), lattice_db=lattice_db, conv_db=conv_db)
    msg = InboundMessage(
        source_e164="+19105813970", timestamp_ms=1, body="morning",
        attachment_paths=(),
    )
    with patch.object(daemon, "_ensure_session", return_value="sess-1"), \
         patch.object(daemon, "_call_vnext_chat", return_value="morning back."), \
         patch("soveryn.agents.signal_bridge.daemon.send_once") as mock_send:
        daemon._handle_inbound(msg)
    mock_send.assert_called_once()
    kwargs = mock_send.call_args.kwargs
    assert kwargs["recipient_e164"] == "+19105813970"
    assert kwargs["body"] == "morning back."
    # Two audit rows: inbound + outbound (no dropped).
    with sqlite3.connect(str(lattice_db)) as con:
        directions = [r[0] for r in con.execute(
            "SELECT direction FROM signal_log ORDER BY created_at"
        ).fetchall()]
    assert directions == ["inbound", "outbound"]


def test_daemon_retries_outbound_with_backoff(lattice_db, conv_db):
    """First two sends raise, third succeeds. Audit row reports success."""
    daemon = SignalBridgeDaemon(_config(), lattice_db=lattice_db, conv_db=conv_db)
    msg = InboundMessage(
        source_e164="+19105813970", timestamp_ms=1, body="ping",
        attachment_paths=(),
    )
    send_side_effects = [SignalCliError("transient 1"), SignalCliError("transient 2"), None]
    with patch.object(daemon, "_ensure_session", return_value="sess-1"), \
         patch.object(daemon, "_call_vnext_chat", return_value="pong"), \
         patch("soveryn.agents.signal_bridge.daemon.send_once",
                side_effect=send_side_effects) as mock_send:
        daemon._handle_inbound(msg)
    assert mock_send.call_count == 3
    with sqlite3.connect(str(lattice_db)) as con:
        last_outbound_error = con.execute(
            "SELECT error FROM signal_log WHERE direction='outbound' "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()[0]
    assert last_outbound_error is None  # last attempt succeeded


def test_daemon_records_outbound_failure_after_all_retries_exhausted(lattice_db, conv_db):
    daemon = SignalBridgeDaemon(_config(), lattice_db=lattice_db, conv_db=conv_db)
    msg = InboundMessage(
        source_e164="+19105813970", timestamp_ms=1, body="ping",
        attachment_paths=(),
    )
    persistent_err = SignalCliError("always broken")
    with patch.object(daemon, "_ensure_session", return_value="sess-1"), \
         patch.object(daemon, "_call_vnext_chat", return_value="pong"), \
         patch("soveryn.agents.signal_bridge.daemon.send_once",
                side_effect=persistent_err) as mock_send:
        daemon._handle_inbound(msg)
    assert mock_send.call_count == 3  # outbound_max_retries
    with sqlite3.connect(str(lattice_db)) as con:
        last_outbound_error = con.execute(
            "SELECT error FROM signal_log WHERE direction='outbound' "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()[0]
    assert last_outbound_error is not None
    assert "always broken" in last_outbound_error


def test_daemon_skips_send_when_aetheria_returns_empty(lattice_db, conv_db):
    """Aetheria empty content → audit-row the failure, do NOT call send_once."""
    daemon = SignalBridgeDaemon(_config(), lattice_db=lattice_db, conv_db=conv_db)
    msg = InboundMessage(
        source_e164="+19105813970", timestamp_ms=1, body="anything",
        attachment_paths=(),
    )
    with patch.object(daemon, "_ensure_session", return_value="sess-1"), \
         patch.object(daemon, "_call_vnext_chat", return_value="   "), \
         patch("soveryn.agents.signal_bridge.daemon.send_once") as mock_send:
        daemon._handle_inbound(msg)
    mock_send.assert_not_called()
    with sqlite3.connect(str(lattice_db)) as con:
        last_outbound = con.execute(
            "SELECT error FROM signal_log WHERE direction='outbound' "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    assert last_outbound[0] == "empty response from Aetheria"


def test_daemon_dispatches_attachment_only_message_with_placeholder(lattice_db, conv_db):
    """Image-only message (body=='', attachments=N) gets dispatched with a
    placeholder body so Aetheria sees that an attachment came in."""
    daemon = SignalBridgeDaemon(_config(), lattice_db=lattice_db, conv_db=conv_db)
    msg = InboundMessage(
        source_e164="+19105813970", timestamp_ms=1, body="",
        attachment_paths=("att-1.jpg",),
    )
    captured = {}
    def fake_chat(session_id, body):
        captured["body"] = body
        return "got the pic"
    with patch.object(daemon, "_ensure_session", return_value="sess-1"), \
         patch.object(daemon, "_call_vnext_chat", side_effect=fake_chat), \
         patch("soveryn.agents.signal_bridge.daemon.send_once"):
        daemon._handle_inbound(msg)
    assert "1 attachment(s)" in captured["body"]
