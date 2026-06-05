"""Tests for the Aetheria-initiated signal_send tool — allowlist gate,
default recipient, audit row, structured error on signal-cli failure.

Subprocess is mocked. The live signal-cli send is exercised by manual
verification, not the unit suite.
"""

from __future__ import annotations

import sqlite3
from unittest.mock import patch

import pytest

from soveryn.agents.signal_bridge.client import SignalCliError
from soveryn.agents.signal_bridge.config import SignalBridgeConfig
from soveryn.agents.signal_bridge.tools import (
    build_signal_send_tool,
    register_signal_send_tool,
)
from soveryn.platform.lattice.legacy import LatticeStore
from soveryn.platform.tools.registry import ToolArgError, ToolRegistry


@pytest.fixture
def lattice_db(tmp_path):
    db = tmp_path / "lattice.db"
    LatticeStore(db)
    return db


def _config(allowed=("+19105813970",)) -> SignalBridgeConfig:
    return SignalBridgeConfig(
        bot_number="+19102489392",
        allowed_numbers=frozenset(allowed),
        signal_cli_bin="/usr/local/bin/signal-cli",
        vnext_base="http://127.0.0.1:5001",
        chat_timeout_seconds=240,
        enabled=True,
        poll_interval_seconds=2.0,
        outbound_max_retries=3,
        outbound_initial_backoff_seconds=0.01,
    )


# ─── Validation ─────────────────────────────────────────────────────────────

def test_signal_send_rejects_empty_message(lattice_db):
    tool = build_signal_send_tool(config=_config(), lattice_db_path=lattice_db)
    with pytest.raises(ToolArgError, match="non-empty"):
        tool.handler({"message": ""})
    with pytest.raises(ToolArgError, match="non-empty"):
        tool.handler({"message": "   "})
    with pytest.raises(ToolArgError):
        tool.handler({})


def test_signal_send_rejects_off_allowlist_recipient(lattice_db):
    tool = build_signal_send_tool(config=_config(), lattice_db_path=lattice_db)
    with pytest.raises(ToolArgError, match="not in allowlist"):
        tool.handler({"message": "hi", "recipient": "+15555550199"})


def test_signal_send_rejects_when_no_default_and_no_recipient(lattice_db):
    """Empty allowlist + no recipient = nowhere to send."""
    cfg = _config(allowed=())
    tool = build_signal_send_tool(config=cfg, lattice_db_path=lattice_db)
    with pytest.raises(ToolArgError, match="recipient"):
        tool.handler({"message": "hi"})


# ─── Default recipient ──────────────────────────────────────────────────────

def test_signal_send_uses_default_recipient_when_omitted(lattice_db):
    tool = build_signal_send_tool(config=_config(), lattice_db_path=lattice_db)
    with patch("soveryn.agents.signal_bridge.tools.send_once") as mock_send:
        result = tool.handler({"message": "morning"})
    mock_send.assert_called_once()
    assert mock_send.call_args.kwargs["recipient_e164"] == "+19105813970"
    assert result["sent"] is True
    assert result["recipient"] == "+19105813970"


def test_signal_send_picks_first_allowlisted_when_multiple(lattice_db):
    """Multiple allowlisted numbers → first sorted is the default."""
    cfg = _config(allowed=("+15555550100", "+19105813970"))
    tool = build_signal_send_tool(config=cfg, lattice_db_path=lattice_db)
    with patch("soveryn.agents.signal_bridge.tools.send_once") as mock_send:
        tool.handler({"message": "hi"})
    # Sorted: "+15555550100" < "+19105813970"
    assert mock_send.call_args.kwargs["recipient_e164"] == "+15555550100"


# ─── Audit log ──────────────────────────────────────────────────────────────

def test_signal_send_success_writes_outbound_row(lattice_db):
    tool = build_signal_send_tool(config=_config(), lattice_db_path=lattice_db)
    with patch("soveryn.agents.signal_bridge.tools.send_once"):
        tool.handler({"message": "test message"})
    with sqlite3.connect(str(lattice_db)) as con:
        rows = con.execute(
            "SELECT direction, sender_e164, recipient_e164, error, body_head "
            "FROM signal_log"
        ).fetchall()
    assert len(rows) == 1
    direction, sender, recipient, error, body_head = rows[0]
    assert direction == "outbound"
    assert sender == "+19102489392"
    assert recipient == "+19105813970"
    assert error is None
    assert body_head == "test message"


def test_signal_send_failure_returns_structured_error_and_audits(lattice_db):
    """signal-cli send failure → {error, message} result + audit row with error."""
    tool = build_signal_send_tool(config=_config(), lattice_db_path=lattice_db)
    with patch(
        "soveryn.agents.signal_bridge.tools.send_once",
        side_effect=SignalCliError("network down"),
    ):
        result = tool.handler({"message": "hi"})
    assert result["error"] == "send_failed"
    assert "network down" in result["message"]
    assert result["recipient"] == "+19105813970"
    with sqlite3.connect(str(lattice_db)) as con:
        rows = con.execute(
            "SELECT direction, error FROM signal_log"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "outbound"
    assert "network down" in rows[0][1]


# ─── Registration + schema ─────────────────────────────────────────────────

def test_register_signal_send_adds_for_aetheria(lattice_db):
    registry = ToolRegistry()
    register_signal_send_tool(
        registry, config=_config(), lattice_db_path=lattice_db,
        owner_agent="aetheria",
    )
    schemas = registry.iter_tools_for_agent("aetheria")
    names = {s.name for s in schemas}
    assert "signal_send" in names


def test_signal_send_does_not_leak_to_other_agents(lattice_db):
    registry = ToolRegistry()
    register_signal_send_tool(
        registry, config=_config(), lattice_db_path=lattice_db,
        owner_agent="aetheria",
    )
    for other in ("vett", "scotty"):
        other_tools = {s.name for s in registry.iter_tools_for_agent(other)}
        assert "signal_send" not in other_tools


def test_signal_send_schema_marks_message_required(lattice_db):
    tool = build_signal_send_tool(config=_config(), lattice_db_path=lattice_db)
    assert "message" in tool.schema["required"]
    assert "recipient" not in tool.schema["required"]
