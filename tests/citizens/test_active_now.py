"""Unit tests for Active-now aggregator."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from soveryn.citizens import commissions
from soveryn.citizens.active_now import build_active_now
from soveryn.citizens.registry import Citizen, connect, register
from soveryn.memory.conversation_store import ConversationStore


@pytest.fixture
def citizens_db(tmp_path: Path) -> Path:
    db = tmp_path / "citizens.db"
    with connect(db) as conn:
        register(
            conn,
            Citizen(
                id="aetheria",
                display_name="Aetheria",
                workspace_path=str(tmp_path / "desks" / "aetheria"),
            ),
        )
        register(
            conn,
            Citizen(
                id="eve",
                display_name="Eve",
                workspace_path=str(tmp_path / "desks" / "eve"),
            ),
        )
    return db


def test_empty_house(citizens_db: Path, tmp_path: Path) -> None:
    conv = ConversationStore(tmp_path / "conv.db")
    out = build_active_now(citizens_db, conv.db_path)
    assert out["count"] == 0
    assert out["active"] == []


def test_running_heartbeat_commission(citizens_db: Path, tmp_path: Path) -> None:
    with connect(citizens_db) as conn:
        commissions.begin_owned(
            conn,
            "aetheria",
            "heartbeat pulse",
            worker="heartbeat",
            at="2026-08-20T12:00:00Z",
        )
    out = build_active_now(citizens_db, None)
    assert out["count"] == 1
    chip = out["active"][0]
    assert chip["citizen"] == "aetheria"
    assert chip["kind"] == "heartbeat"
    assert chip["label"] == "Aetheria · heartbeat"
    assert chip["since"] == "2026-08-20T12:00:00Z"


def test_running_discrete_commission(citizens_db: Path) -> None:
    with connect(citizens_db) as conn:
        commissions.begin_owned(
            conn,
            "eve",
            "draft the caption",
            worker="citizens-runtime/eve",
            at="2026-08-20T12:05:00Z",
        )
    out = build_active_now(citizens_db, None)
    assert out["count"] == 1
    assert out["active"][0]["kind"] == "commission"
    assert out["active"][0]["label"] == "Eve · commission"


def test_interactive_chat_busy(citizens_db: Path, tmp_path: Path) -> None:
    conv = ConversationStore(tmp_path / "conv.db")
    sid = conv.new_session("aetheria")
    conv.save_turn(sid, "aetheria", "user", "hey", source="direct")
    out = build_active_now(citizens_db, conv.db_path, within_seconds=90)
    kinds = {c["kind"] for c in out["active"] if c["citizen"] == "aetheria"}
    assert "chat" in kinds
    chat = next(c for c in out["active"] if c["kind"] == "chat")
    assert chat["label"] == "Aetheria · chat"


def test_parked_citizens_do_not_appear(citizens_db: Path) -> None:
    with connect(citizens_db) as conn:
        register(
            conn,
            Citizen(
                id="scotty",
                display_name="Scotty",
                workspace_path=str(citizens_db.parent / "desks" / "scotty"),
            ),
        )
        commissions.begin_owned(
            conn,
            "scotty",
            "desk drain",
            worker="scotty-worker",
            at="2026-08-20T12:00:00Z",
        )
    out = build_active_now(citizens_db, None)
    assert all(c["citizen"] != "scotty" for c in out["active"])
    assert all(c["citizen"] != "vett" for c in out["active"])


def test_missing_db_is_empty_not_raise(tmp_path: Path) -> None:
    out = build_active_now(tmp_path / "nope.db", None)
    assert out["count"] == 0
    assert "note" in out
