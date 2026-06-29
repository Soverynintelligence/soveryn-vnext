"""Tests for /api/steward/board route.

Client fixture pattern mirrors test_app_api_system_routes.py:
  - create_app with a minimal conv_store + fake agent_loops
  - SOVERYN_DATA_ROOT monkeypatched to a tmp_path so the route resolves
    env.data_root / "steward" / "grants.json" cleanly in isolation

Two fixture variants:
  - client_with_grants:  a seeded grants.json (milestone cadence, two entries)
  - client_no_grants:    no steward/ directory at all → FileNotFoundError path
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from soveryn.agents.loop import AgentLoop
from soveryn.app.startup import create_app
from soveryn.config.runtime import ACTIVE_AGENTS
from soveryn.inference.llama_server_client import ChatResponse
from soveryn.memory.conversation_store import ConversationStore


# ─── Shared helpers ───────────────────────────────────────────────────────────

@pytest.fixture
def fake_chat():
    return lambda req, server, timeout=60: ChatResponse(
        content="ok", finish_reason="stop", tool_calls=None, usage=None, raw={}
    )


def _make_client(tmp_path: Path, fake_chat, monkeypatch, *, seed_grants: bool):
    """Build a test client, optionally seeding data/steward/grants.json."""
    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    if seed_grants:
        steward_dir = tmp_path / "steward"
        steward_dir.mkdir(parents=True, exist_ok=True)
        grants = [
            {
                "funder": "Test Funder A",
                "award_id": "GRANT-A",
                "title": "Test Grant A",
                "period_start": "2025-01-01",
                "period_end": "2027-01-01",
                "reporting_cadence": "milestone",
                "milestones": [
                    ["2026-08-01", "Submit phase-1 report"],
                    ["2099-01-01", "Far-future milestone (well inside horizon)"],
                ],
                "award_amount": 50000,
            },
            {
                "funder": "Test Funder B",
                "award_id": "GRANT-B",
                "title": "Test Grant B",
                "period_start": "2025-01-01",
                "period_end": "2026-12-31",
                "reporting_cadence": "milestone",
                "milestones": [
                    # Use a date within the 365-day lookback window from today.
                    # "2026-01-01" is ~179 days before 2026-06-29 — always in lookback.
                    ["2026-01-01", "Overdue milestone"],
                ],
                "award_amount": None,
            },
        ]
        (steward_dir / "grants.json").write_text(json.dumps(grants), encoding="utf-8")

    conv = ConversationStore(tmp_path / "conv.db")
    loops = {n: AgentLoop(n, conv, chat_fn=fake_chat) for n in ACTIVE_AGENTS}
    app = create_app(conv_store=conv, agent_loops=loops)
    app.config["SOVERYN_REQUIRE_LOCALHOST"] = False
    return app.test_client()


@pytest.fixture
def client_with_grants(tmp_path, fake_chat, monkeypatch):
    return _make_client(tmp_path, fake_chat, monkeypatch, seed_grants=True)


@pytest.fixture
def client_no_grants(tmp_path, fake_chat, monkeypatch):
    return _make_client(tmp_path, fake_chat, monkeypatch, seed_grants=False)


# ─── Tests: missing config (graceful 200, never 500) ─────────────────────────

def test_missing_grants_returns_200_not_500(client_no_grants):
    resp = client_no_grants.get("/api/steward/board")
    assert resp.status_code == 200


def test_missing_grants_config_present_false(client_no_grants):
    resp = client_no_grants.get("/api/steward/board")
    data = resp.get_json()
    assert data["config_present"] is False


def test_missing_grants_empty_entries(client_no_grants):
    resp = client_no_grants.get("/api/steward/board")
    data = resp.get_json()
    assert data["entries"] == []


def test_missing_grants_has_as_of(client_no_grants):
    resp = client_no_grants.get("/api/steward/board")
    data = resp.get_json()
    assert "as_of" in data
    assert len(data["as_of"]) == 10  # YYYY-MM-DD


# ─── Tests: seeded grants ─────────────────────────────────────────────────────

def test_board_returns_200(client_with_grants):
    resp = client_with_grants.get("/api/steward/board")
    assert resp.status_code == 200


def test_board_is_json(client_with_grants):
    resp = client_with_grants.get("/api/steward/board")
    assert resp.is_json


def test_board_config_present_true(client_with_grants):
    resp = client_with_grants.get("/api/steward/board")
    data = resp.get_json()
    assert data["config_present"] is True


def test_board_has_as_of(client_with_grants):
    resp = client_with_grants.get("/api/steward/board")
    data = resp.get_json()
    assert "as_of" in data
    assert len(data["as_of"]) == 10


def test_board_entries_sorted_by_due_date(client_with_grants):
    resp = client_with_grants.get("/api/steward/board?days=99999")
    data = resp.get_json()
    entries = data["entries"]
    assert len(entries) >= 2
    due_dates = [e["due_date"] for e in entries]
    assert due_dates == sorted(due_dates)


def test_board_entries_have_required_fields(client_with_grants):
    resp = client_with_grants.get("/api/steward/board?days=99999")
    data = resp.get_json()
    required = {"award_id", "funder", "label", "due_date", "days_out", "status", "amount"}
    for entry in data["entries"]:
        assert required.issubset(entry.keys()), f"Missing fields in entry: {entry}"


def test_board_days_out_is_int(client_with_grants):
    resp = client_with_grants.get("/api/steward/board?days=99999")
    data = resp.get_json()
    for entry in data["entries"]:
        assert isinstance(entry["days_out"], int)


def test_board_overdue_has_negative_days_out(client_with_grants):
    """GRANT-B's milestone is 2025-06-01 — firmly overdue."""
    resp = client_with_grants.get("/api/steward/board?days=99999")
    data = resp.get_json()
    overdue = [e for e in data["entries"] if e["status"] == "overdue"]
    assert len(overdue) >= 1
    for e in overdue:
        assert e["days_out"] < 0


def test_board_done_items_excluded(tmp_path, fake_chat, monkeypatch):
    """Obligations with status='done' must not appear in entries.

    compute_grant_schedule never returns done (that's the apply_submissions
    overlay), but we verify that if the engine somehow produced one, the
    route filters it. We achieve this by patching the engine function.
    """
    from unittest.mock import patch
    from datetime import date
    from soveryn.platform.steward.engine import GrantObligation

    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    steward_dir = tmp_path / "steward"
    steward_dir.mkdir(parents=True, exist_ok=True)
    # A valid minimal grant so load_grants succeeds
    grants = [{
        "funder": "F", "award_id": "G1", "title": "T",
        "period_start": "2025-01-01", "period_end": "2027-01-01",
        "reporting_cadence": "milestone",
        "milestones": [["2026-08-01", "Draft"]],
        "award_amount": None,
    }]
    (steward_dir / "grants.json").write_text(json.dumps(grants), encoding="utf-8")

    conv = ConversationStore(tmp_path / "conv.db")
    loops = {n: AgentLoop(n, conv, chat_fn=fake_chat) for n in ACTIVE_AGENTS}
    app = create_app(conv_store=conv, agent_loops=loops)
    app.config["SOVERYN_REQUIRE_LOCALHOST"] = False

    done_ob = GrantObligation(
        award_id="G1", funder="F", title="T",
        report_label="Draft", due_date=date(2026, 8, 1),
        status="done",
    )
    upcoming_ob = GrantObligation(
        award_id="G1", funder="F", title="T",
        report_label="Draft", due_date=date(2026, 8, 1),
        status="upcoming",
    )

    with patch(
        "soveryn.app.routes.api_steward.compute_grant_schedule",
        return_value=[done_ob, upcoming_ob],
    ):
        client = app.test_client()
        resp = client.get("/api/steward/board")

    data = resp.get_json()
    assert resp.status_code == 200
    statuses = [e["status"] for e in data["entries"]]
    assert "done" not in statuses
    assert "upcoming" in statuses


def test_board_amount_present(client_with_grants):
    """GRANT-A has award_amount 50000; GRANT-B has null."""
    resp = client_with_grants.get("/api/steward/board?days=99999")
    data = resp.get_json()
    grant_a = next((e for e in data["entries"] if e["award_id"] == "GRANT-A"), None)
    grant_b = next((e for e in data["entries"] if e["award_id"] == "GRANT-B"), None)
    assert grant_a is not None
    assert grant_a["amount"] == 50000
    if grant_b is not None:
        assert grant_b["amount"] is None


def test_board_default_days_param(client_with_grants):
    """Default horizon (400d) excludes the 2099 far-future milestone."""
    resp = client_with_grants.get("/api/steward/board")
    data = resp.get_json()
    # 2099-01-01 is ~27,000+ days out — well beyond 400d horizon
    far_future = [e for e in data["entries"] if e["due_date"].startswith("2099")]
    assert far_future == []


def test_board_custom_days_extends_horizon(client_with_grants):
    """?days=99999 brings the 2099 milestone in."""
    resp = client_with_grants.get("/api/steward/board?days=99999")
    data = resp.get_json()
    far_future = [e for e in data["entries"] if e["due_date"].startswith("2099")]
    assert len(far_future) == 1
