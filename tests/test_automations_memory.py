"""Cron-that-remembers: continuity, notepad, monitor skip, acked failures."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from soveryn.automations.memory import (
    MAX_KEY_CHARS,
    MAX_VALUE_BYTES,
    ack_incident,
    assemble_run_prompt,
    check_monitor,
    delete_note,
    get_note,
    is_failure_acked,
    is_silent,
    list_notes,
    load_last_output,
    prepare_run,
    render_continuity_section,
    render_notepad_section,
    save_last_output,
    set_note,
    upsert_incident,
)
from soveryn.automations.registry import AutomationSpec, Delivery
from soveryn.automations.runner import run_automation


def _spec(**kwargs) -> AutomationSpec:
    defaults = dict(
        id="morning_brief",
        title="Morning Brief",
        category="news",
        agent="aetheria",
        cron="30 7 * * *",
        prompt="Compose the morning brief.",
        delivery=Delivery(channel="signal", target="jon"),
    )
    defaults.update(kwargs)
    return AutomationSpec(**defaults)


def test_empty_last_output_is_no_continuity_section(tmp_path, monkeypatch):
    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    assert load_last_output("morning_brief") == ""
    assert render_continuity_section("morning_brief") == ""


def test_save_and_inject_last_output_continuity(tmp_path, monkeypatch):
    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    save_last_output("morning_brief", "Lead: markets quiet.\nItem 2: GLM bake.")
    section = render_continuity_section("morning_brief")
    assert "previous run" in section.lower()
    assert "markets quiet" in section
    prompt = assemble_run_prompt(_spec())
    assert "markets quiet" in prompt
    assert "Compose the morning brief." in prompt
    assert prompt.index("markets quiet") < prompt.index("Compose the morning brief.")


def test_continuity_truncated(tmp_path, monkeypatch):
    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    save_last_output("morning_brief", "x" * 20_000)
    loaded = load_last_output("morning_brief")
    assert len(loaded) <= 8000 + 80  # cap plus truncation marker
    assert loaded.endswith("[... output truncated ...]") or len(loaded) == 8000


def test_notepad_set_get_list_delete(tmp_path, monkeypatch):
    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    set_note("morning_brief", "cursor", "story:glm-bake")
    assert get_note("morning_brief", "cursor") == "story:glm-bake"
    rows = list_notes("morning_brief")
    assert rows[0]["key"] == "cursor"
    assert render_notepad_section("morning_brief").startswith("## Job notepad")
    assert "story:glm-bake" in render_notepad_section("morning_brief")
    assert delete_note("morning_brief", "cursor") is True
    assert get_note("morning_brief", "cursor") is None
    assert render_notepad_section("morning_brief") == ""


def test_notepad_empty_keeps_prompt_without_section(tmp_path, monkeypatch):
    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    prompt = assemble_run_prompt(_spec())
    assert "## Job notepad" not in prompt
    assert "Compose the morning brief." in prompt


def test_notepad_size_caps(tmp_path, monkeypatch):
    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    with pytest.raises(ValueError):
        set_note("morning_brief", "k", "x" * (MAX_VALUE_BYTES + 1))
    with pytest.raises(ValueError):
        set_note("morning_brief", "k" * (MAX_KEY_CHARS + 1), "v")
    chunk = "y" * (MAX_VALUE_BYTES - 8)
    for i in range(4):
        set_note("morning_brief", str(i), chunk)
    with pytest.raises(ValueError, match="notepad full"):
        set_note("morning_brief", "4", chunk)


def test_monitor_skips_when_hash_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    watch = tmp_path / "automations" / "watches" / "pond_academy.txt"
    watch.parent.mkdir(parents=True)
    watch.write_text("apex dropped a 14ft kit\n", encoding="utf-8")
    spec = _spec(
        id="pond_academy_watch",
        title="Pond Academy Watch",
        category="ops",
        agent="eve",
        cron="0 7 * * *",
        prompt="Report pond academy changes only.",
        monitor_file="automations/watches/pond_academy.txt",
    )
    first = check_monitor(spec)
    assert first.ok is True
    assert first.changed is True
    assert first.first_run is True
    assert "apex dropped" in (first.context_block or "")

    second = check_monitor(spec)
    assert second.ok is True
    assert second.changed is False
    assert second.context_block is None

    watch.write_text("apex dropped a 14ft kit\nplus a pump SKU\n", encoding="utf-8")
    third = check_monitor(spec)
    assert third.ok is True
    assert third.changed is True
    assert "MONITOR CHANGE DETECTED" in (third.context_block or "")
    assert "pump SKU" in (third.context_block or "")


def test_monitor_source_failure_does_not_update_hash(tmp_path, monkeypatch):
    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    spec = _spec(
        id="pond_academy_watch",
        title="Pond Academy Watch",
        category="ops",
        agent="eve",
        cron="0 7 * * *",
        prompt="Report pond academy changes only.",
        monitor_url="https://example.invalid/watch",
    )
    calls = {"n": 0}

    def fetch(url: str):
        calls["n"] += 1
        if calls["n"] == 1:
            return True, "stable page"
        return False, "timeout"

    first = check_monitor(spec, fetch_fn=fetch)
    assert first.changed is True
    failed = check_monitor(spec, fetch_fn=fetch)
    assert failed.ok is False
    assert "timeout" in (failed.error or "")

    def fetch_stable(url: str):
        return True, "stable page"

    recovered = check_monitor(spec, fetch_fn=fetch_stable)
    assert recovered.ok is True
    assert recovered.changed is False


def test_monitor_missing_file_does_not_spend_llm(tmp_path, monkeypatch):
    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    spec = _spec(
        id="pond_academy_watch",
        title="Pond Academy Watch",
        category="ops",
        agent="eve",
        cron="0 7 * * *",
        prompt="Report pond academy changes only.",
        monitor_file="automations/watches/pond_academy.txt",
    )
    prep = prepare_run(spec)
    assert prep.skip is True
    assert prep.reason == "no_change"


def test_acked_failure_same_signature_stays_acked(tmp_path, monkeypatch):
    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    iid, is_new = upsert_incident("morning_brief", "LlamaServerTimeout: 600s")
    assert is_new is True
    assert is_failure_acked("morning_brief", "LlamaServerTimeout: 600s") is False
    assert ack_incident(iid) is True
    assert is_failure_acked("morning_brief", "LlamaServerTimeout: 600s") is True
    iid2, is_new2 = upsert_incident("morning_brief", "LlamaServerTimeout: 600s")
    assert is_new2 is False
    assert iid2 == iid
    assert is_failure_acked("morning_brief", "LlamaServerTimeout: 600s") is True


def test_new_error_mints_fresh_unacked_incident(tmp_path, monkeypatch):
    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    iid, _ = upsert_incident("morning_brief", "timeout")
    ack_incident(iid)
    iid2, is_new = upsert_incident("morning_brief", "401 unauthorized")
    assert is_new is True
    assert iid2 != iid
    assert is_failure_acked("morning_brief", "401 unauthorized") is False


def test_silent_marker():
    assert is_silent("[SILENT]") is True
    assert is_silent("  [SILENT]\n") is True
    assert is_silent("[SILENT] plus news") is False
    assert is_silent("nothing new") is False


def test_prepare_run_injects_notepad_and_continuity(tmp_path, monkeypatch):
    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    save_last_output("morning_brief", "Yesterday: GLM EXL3 restored.")
    set_note("morning_brief", "watchlist", "flash bake")
    prep = prepare_run(_spec())
    assert prep.skip is False
    assert "Yesterday: GLM EXL3 restored." in prep.prompt
    assert "flash bake" in prep.prompt
    assert "[SILENT]" in prep.prompt


class _FakeLoop:
    def __init__(self):
        self.prompts: list[str] = []

    def process_message(self, session_id, prompt, source=None):
        self.prompts.append(prompt)
        return SimpleNamespace(
            content="Lead: quiet tape.",
            finish_reason="stop",
            tool_calls=None,
            usage=None,
            context_usage=None,
        )


class _FakeStore:
    def list_sessions(self, agent=None, limit=200):
        return []

    def new_session(self, agent, title=None):
        return "sess-auto-1"


def test_live_run_records_last_output_and_injects_next_time(tmp_path, monkeypatch):
    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    loop = _FakeLoop()
    store = _FakeStore()
    first = run_automation(
        "morning_brief", dry_run=False, agent_loop=loop, conv_store=store
    )
    assert first["status"] == "ok"
    assert first["content"] == "Lead: quiet tape."
    assert load_last_output("morning_brief") == "Lead: quiet tape."
    assert "## Your previous run's output" not in loop.prompts[0]

    second = run_automation(
        "morning_brief", dry_run=False, agent_loop=loop, conv_store=store
    )
    assert second["status"] == "ok"
    assert "## Your previous run's output" in loop.prompts[1]
    assert "Lead: quiet tape." in loop.prompts[1]


def test_live_monitor_skip_does_not_call_model(tmp_path, monkeypatch):
    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    watch = tmp_path / "automations" / "watches" / "pond_academy.txt"
    watch.parent.mkdir(parents=True)
    watch.write_text("same\n", encoding="utf-8")
    loop = _FakeLoop()
    store = _FakeStore()
    first = run_automation(
        "pond_academy_watch",
        dry_run=False,
        agent_loop=loop,
        conv_store=store,
    )
    assert first["status"] == "ok"
    assert loop.prompts  # first observation spends a turn
    loop.prompts.clear()
    skipped = run_automation(
        "pond_academy_watch",
        dry_run=False,
        agent_loop=loop,
        conv_store=store,
    )
    assert skipped["status"] == "no_change"
    assert loop.prompts == []
    assert skipped.get("content") in ("", None)


def test_should_write_inbox_skips_no_change_silent_and_acked(tmp_path, monkeypatch):
    from soveryn.automations.memory import should_write_inbox

    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    assert should_write_inbox({"id": "morning_brief", "status": "no_change"}) is False
    assert should_write_inbox(
        {"id": "morning_brief", "status": "ok", "content": "[SILENT]"}
    ) is False
    assert should_write_inbox(
        {"id": "morning_brief", "status": "ok", "content": "Lead: markets."}
    ) is True
    iid, _ = upsert_incident("morning_brief", "LlamaServerTimeout")
    ack_incident(iid)
    assert should_write_inbox(
        {
            "id": "morning_brief",
            "status": "error",
            "message": "LlamaServerTimeout",
        }
    ) is False


def test_cron_notepad_tool_uses_bound_job(tmp_path, monkeypatch):
    from soveryn.automations.notepad_tool import (
        build_cron_notepad_tool,
        current_automation_id,
    )

    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    tool = build_cron_notepad_tool(owner_agent="aetheria")
    token = current_automation_id.set("morning_brief")
    try:
        out = tool.handler({"action": "set", "key": "cursor", "value": "glm"})
        assert out["ok"] is True
        listed = tool.handler({"action": "list"})
        assert listed["notes"][0]["value"] == "glm"
    finally:
        current_automation_id.reset(token)
