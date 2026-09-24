"""ActTruth Step 3 — bug triage queue from soft lessons."""
from __future__ import annotations

from datetime import datetime, timedelta

from soveryn.platform.acttruth.triage import (
    enqueue_from_lesson,
    enqueue_if_lesson,
    list_triage,
    suggest_correction_type,
)


def test_suggest_correction_types():
    assert suggest_correction_type("bad_args") == "skill"
    assert suggest_correction_type("timeout") == "ops"
    assert suggest_correction_type("permission") == "ask_jon"
    assert suggest_correction_type("weird") == "code"


def test_enqueue_and_list(tmp_path, monkeypatch):
    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    row = enqueue_from_lesson(
        agent="vett",
        tool="web_search",
        error_class="timeout",
        streak=2,
        pattern="web_search::timeout",
        summary="timed out",
        lesson_text="LESSON: web_search failed 2× as timeout",
        data_root=tmp_path,
    )
    assert row is not None
    assert row["status"] == "open"
    assert row["correction_type"] == "ops"
    assert row["owner"] == "aetheria"
    items = list_triage(data_root=tmp_path)
    assert len(items) == 1
    assert items[0]["id"] == row["id"]


def test_cooldown_dedupes(tmp_path, monkeypatch):
    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    kwargs = dict(
        agent="aetheria",
        tool="fetch_url",
        error_class="unreachable",
        streak=2,
        pattern="fetch_url::unreachable",
        summary="connection refused",
        data_root=tmp_path,
    )
    first = enqueue_from_lesson(**kwargs)
    second = enqueue_from_lesson(**kwargs)
    assert first is not None
    assert second is None
    assert len(list_triage(data_root=tmp_path)) == 1


def test_enqueue_if_lesson_parses_streak(tmp_path, monkeypatch):
    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    row = enqueue_if_lesson(
        agent="scotty",
        tool="run_command",
        lesson_text="LESSON: `run_command` failed 3× as `bad_args`. Do NOT repeat.",
        error="ToolArgError: must be absolute",
        data_root=tmp_path,
    )
    assert row is not None
    assert row["streak"] == 3
    assert row["correction_type"] == "skill"
    assert row["owner"] == "vett" or row["owner"] == "scotty"


def test_api_triage_endpoint(tmp_path, monkeypatch, fake_chat):
    from soveryn.agents.loop import AgentLoop
    from soveryn.app.startup import create_app
    from soveryn.config.runtime import ACTIVE_AGENTS
    from soveryn.memory.conversation_store import ConversationStore

    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    enqueue_from_lesson(
        agent="vett",
        tool="web_search",
        error_class="timeout",
        streak=2,
        pattern="web_search::timeout",
        summary="t",
        data_root=tmp_path,
        now=datetime.now() - timedelta(seconds=1),
    )
    conv = ConversationStore(tmp_path / "conv.db")
    loops = {n: AgentLoop(n, conv, chat_fn=fake_chat) for n in ACTIVE_AGENTS}
    app = create_app(conv_store=conv, agent_loops=loops)
    app.config["SOVERYN_REQUIRE_LOCALHOST"] = False
    client = app.test_client()
    resp = client.get("/api/system/acttruth/triage")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["count"] >= 1
    assert data["triage"][0]["tool"] == "web_search"
