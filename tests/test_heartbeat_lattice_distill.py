"""Heartbeat lattice write stores distill + Channel-A provenance (PR3)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from soveryn.agents.heartbeat import HeartbeatConfig
from soveryn.agents.heartbeat.daemon import HeartbeatDaemon
from soveryn.agents.heartbeat.prompt import BoardSnapshot, LatticeSnapshot
from soveryn.platform.lattice.legacy import LatticeStore


@pytest.fixture()
def house(tmp_path):
    lattice = tmp_path / "lattice.db"
    LatticeStore(lattice)
    thoughts = tmp_path / "heartbeat_thoughts.jsonl"
    thoughts.write_text("", encoding="utf-8")
    return tmp_path, lattice, thoughts


def test_heartbeat_writes_distill_not_full_essay(house):
    tmp_path, lattice, thoughts = house
    cfg = HeartbeatConfig(
        enabled=True,
        dry_run=False,
        interval_seconds=1800,
        backoff_seconds=600,
        quiet_hours="",
    )
    daemon = HeartbeatDaemon(
        cfg,
        lattice_db=lattice,
        thoughts_log_path=thoughts,
        conv_db=tmp_path / "conv.db",
    )
    full_note = (
        "I checked the boards and wandered the dock.\n\n"
        "Standing note: Hold the open blueprint; do not invent a deadline.\n"
    )
    response = {"content": full_note, "tool_calls": None}

    with patch.object(daemon, "_ensure_heartbeat_session", return_value="sess"), \
         patch.object(daemon, "_call_vnext_chat", return_value=response), \
         patch.object(daemon, "_summarise_response", return_value=("note", 0)), \
         patch.object(daemon, "_gather_board_snapshot") as board, \
         patch.object(daemon, "_gather_lattice_snapshot") as lat, \
         patch.object(daemon, "_latest_heartbeat_completed_at", return_value=None), \
         patch.object(daemon, "_gather_material_signals", return_value=[]), \
         patch.object(daemon, "_write_log_row"), \
         patch("soveryn.agents.heartbeat.daemon._gather_salience", return_value=""), \
         patch("soveryn.platform.lattice.legacy.embed_text", return_value=(0.1, 0.2)):
        board.return_value = BoardSnapshot(
            open_signal_count=0, open_blueprint_count=0, ready_blueprint_count=0,
            open_friction_count=0, stalled_blueprint_count=0, blocked_blueprint_count=0,
            oldest_open_signal_age_minutes=None, oldest_open_blueprint_title=None,
            oldest_open_blueprint_age_hours=None,
        )
        lat.return_value = LatticeSnapshot(
            new_node_count_recent_window=0, recent_window_minutes=60,
            new_contradiction_flag_count=0,
        )
        now = datetime(2026, 8, 14, 12, 0, 0, tzinfo=timezone.utc)
        elig = MagicMock()
        elig.eligible = True
        elig.skip_reason = None
        daemon._tick_body(now=now, eligibility=elig)

    store = LatticeStore(lattice)
    nodes = [n for n in store.iter_nodes(agent="aetheria") if n.type == "reflection"]
    assert len(nodes) == 1
    node = nodes[0]
    assert "Hold the open blueprint" in node.content
    assert "wandered the dock" not in node.content
    assert len(node.content) <= 500
    prov = node.provenance if isinstance(node.provenance, dict) else json.loads(node.provenance)
    assert prov["cls"] == "witnessed"
    assert prov["source"] == "heartbeat"
    assert prov["full_text_ref"].startswith("thoughts_log:pulse_id=")
    assert prov["grade"] == "journal"
