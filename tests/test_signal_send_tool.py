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


# ─── Attachments: happy path ─────────────────────────────────────────────────

def test_signal_send_passes_attachment_paths_to_send_once(lattice_db, tmp_path):
    img = tmp_path / "photo.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0fake")

    tool = build_signal_send_tool(config=_config(), lattice_db_path=lattice_db)
    captured: dict = {}
    def fake_send(**kw):
        captured.update(kw)
    with patch("soveryn.agents.signal_bridge.tools.send_once", side_effect=fake_send):
        result = tool.handler({
            "message": "look at this",
            "recipient": "+19105813970",
            "attachments": [str(img)],
        })
    assert result.get("sent") is True
    assert captured["attachments"] == (str(img),)
    # Audit row records the actual attachment count
    with sqlite3.connect(str(lattice_db)) as con:
        row = con.execute(
            "SELECT attachment_count FROM signal_log WHERE direction='outbound'"
        ).fetchone()
    assert row[0] == 1


def test_signal_send_multiple_attachments_preserves_order(lattice_db, tmp_path):
    a = tmp_path / "a.jpg"; a.write_bytes(b"x")
    b = tmp_path / "b.png"; b.write_bytes(b"y")
    tool = build_signal_send_tool(config=_config(), lattice_db_path=lattice_db)
    captured: dict = {}
    def fake_send(**kw):
        captured.update(kw)
    with patch("soveryn.agents.signal_bridge.tools.send_once", side_effect=fake_send):
        tool.handler({
            "message": "two",
            "recipient": "+19105813970",
            "attachments": [str(a), str(b)],
        })
    assert captured["attachments"] == (str(a), str(b))


# ─── Attachments: validation ─────────────────────────────────────────────────

def test_signal_send_rejects_relative_path(lattice_db, tmp_path):
    tool = build_signal_send_tool(config=_config(), lattice_db_path=lattice_db)
    with patch("soveryn.agents.signal_bridge.tools.send_once") as mock_send:
        result = tool.handler({
            "message": "x", "recipient": "+19105813970",
            "attachments": ["relative/path.jpg"],
        })
    assert result.get("error") == "invalid_attachment"
    assert "absolute" in result["message"].lower()
    mock_send.assert_not_called()


def test_signal_send_rejects_path_traversal(lattice_db, tmp_path):
    tool = build_signal_send_tool(config=_config(), lattice_db_path=lattice_db)
    with patch("soveryn.agents.signal_bridge.tools.send_once") as mock_send:
        result = tool.handler({
            "message": "x", "recipient": "+19105813970",
            "attachments": ["/tmp/../etc/passwd"],
        })
    assert result.get("error") == "invalid_attachment"
    assert "traversal" in result["message"].lower() or ".." in result["message"]
    mock_send.assert_not_called()


def test_signal_send_rejects_nonexistent_path(lattice_db, tmp_path):
    ghost = tmp_path / "ghost.jpg"
    tool = build_signal_send_tool(config=_config(), lattice_db_path=lattice_db)
    with patch("soveryn.agents.signal_bridge.tools.send_once") as mock_send:
        result = tool.handler({
            "message": "x", "recipient": "+19105813970",
            "attachments": [str(ghost)],
        })
    assert result.get("error") == "invalid_attachment"
    assert "exist" in result["message"].lower() or "not found" in result["message"].lower()
    mock_send.assert_not_called()


def test_signal_send_rejects_directory_path(lattice_db, tmp_path):
    """Path must be a regular file, not a directory."""
    d = tmp_path / "adir"
    d.mkdir()
    tool = build_signal_send_tool(config=_config(), lattice_db_path=lattice_db)
    with patch("soveryn.agents.signal_bridge.tools.send_once") as mock_send:
        result = tool.handler({
            "message": "x", "recipient": "+19105813970",
            "attachments": [str(d)],
        })
    assert result.get("error") == "invalid_attachment"
    assert "regular file" in result["message"].lower() or "not a" in result["message"].lower()
    mock_send.assert_not_called()


def test_signal_send_rejects_oversized_file(lattice_db, tmp_path):
    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * (17 * 1024 * 1024))  # 17MB
    tool = build_signal_send_tool(config=_config(), lattice_db_path=lattice_db)
    with patch("soveryn.agents.signal_bridge.tools.send_once") as mock_send:
        result = tool.handler({
            "message": "x", "recipient": "+19105813970",
            "attachments": [str(big)],
        })
    assert result.get("error") == "invalid_attachment"
    # message should mention the size cap (16MB or 16777216 or just "size")
    assert "16" in result["message"] or "size" in result["message"].lower()
    mock_send.assert_not_called()


def test_signal_send_rejects_non_list_attachments(lattice_db, tmp_path):
    """Type violation → ToolArgError raise (not structured error)."""
    tool = build_signal_send_tool(config=_config(), lattice_db_path=lattice_db)
    with patch("soveryn.agents.signal_bridge.tools.send_once") as mock_send:
        with pytest.raises(ToolArgError, match="list"):
            tool.handler({
                "message": "x", "recipient": "+19105813970",
                "attachments": "not a list",
            })
    mock_send.assert_not_called()


def test_signal_send_no_attachments_unchanged(lattice_db, tmp_path):
    """Regression: attachments=None preserves prior behavior, no kwarg on send_once."""
    tool = build_signal_send_tool(config=_config(), lattice_db_path=lattice_db)
    captured: dict = {}
    def fake_send(**kw):
        captured.update(kw)
    with patch("soveryn.agents.signal_bridge.tools.send_once", side_effect=fake_send):
        result = tool.handler({
            "message": "text only", "recipient": "+19105813970",
        })
    assert result.get("sent") is True
    # send_once called WITHOUT attachments kwarg (or with empty tuple — either is acceptable)
    if "attachments" in captured:
        assert captured["attachments"] == () or captured["attachments"] == tuple()


def test_signal_send_audit_records_attachment_count(lattice_db, tmp_path):
    """When attachments are passed, the audit row's attachment_count reflects the count."""
    a = tmp_path / "a.jpg"; a.write_bytes(b"x")
    b = tmp_path / "b.png"; b.write_bytes(b"y")
    tool = build_signal_send_tool(config=_config(), lattice_db_path=lattice_db)
    with patch("soveryn.agents.signal_bridge.tools.send_once"):
        tool.handler({
            "message": "two", "recipient": "+19105813970",
            "attachments": [str(a), str(b)],
        })
    with sqlite3.connect(str(lattice_db)) as con:
        row = con.execute(
            "SELECT attachment_count FROM signal_log WHERE direction='outbound'"
        ).fetchone()
    assert row[0] == 2
