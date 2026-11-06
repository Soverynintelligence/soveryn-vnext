"""revamp phases 2-3 on the LIVE pages (2026-11-05, Jon via Atlas): static checks
for message_thread.html (/messages/<agent>) and command_center.html (Desk), plus
the server-side Desk context numbers. Mirrors test_chat_turn_tools_ui.py and
test_chat_context_meter_ui.py, which cover the unserved chat.html reference."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MT = (ROOT / "soveryn/app/templates/message_thread.html").read_text()
CC = (ROOT / "soveryn/app/templates/command_center.html").read_text()


def _code(body: str) -> str:
    return "\n".join(l for l in body.splitlines() if not l.strip().startswith("//"))


def _no_hardcoded_limit(code: str):
    assert not re.search(r"\b\d{4,}\b", code.replace(",", "")), "hardcoded number in meter code"
    assert "innerHTML" not in code


# ── message_thread.html ──
def test_thread_meter_element_and_done_hook():
    assert 'data-testid="context-meter"' in MT
    i = MT.index('} else if (payload.type === "done") {')
    assert "updateContextMeter(payload.context_usage);" in MT[i:i + 120]


def test_thread_meter_reads_server_limit_only():
    start = MT.index("function updateContextMeter")
    code = _code(MT[start:MT.index("const TURN_TOOL_ARG_MAX", start)])
    assert "usage.context_window" in code and "usage.prompt_tokens" in code
    _no_hardcoded_limit(code)


def test_thread_tool_calls_render_as_turn_tools_textcontent():
    i = MT.index('} else if (payload.type === "tool_call") {')
    assert "renderTurnTools(them, turnTools)" in MT[i:i + 400]
    start = MT.index("function toolArgText")
    body = MT[start:MT.index("function appendBubble", start)]
    assert "innerHTML" not in body and "textContent" in body
    assert "reattachTurnTools(sessionId);" in MT


def test_thread_keeps_image_draft_commission_handling():
    for marker in ('payload.name === "generate_image"', "tr.commissioned", 'payload.name === "compose_post"',
                   "house_post_send", "tool_round_limit"):
        assert marker in MT, marker


# ── command_center.html (Desk) ──
def test_desk_meter_element_and_hooks():
    assert 'data-testid="desk-context-meter"' in CC
    assert "deskCtx = i.context || null;" in CC
    i = CC.index('r.type === "message_end"')
    assert "updateDeskMeter(used)" in CC[i:i + 260]


def test_desk_meter_never_hardcodes_a_limit_or_fakes_usage():
    start = CC.index("function promptTokensOf")
    code = _code(CC[start:CC.index("function addTurnTools", start)])
    assert "deskCtx.context_window" in code
    assert "not reported" in code
    _no_hardcoded_limit(code)


def test_desk_history_tools_textcontent():
    start = CC.index("function addTurnTools")
    body = CC[start:CC.index("async function showInfo", start)]
    assert "innerHTML" not in body and "textContent" in body
    assert "addTurnTools(m.tools)" in CC


# ── server: /api/kernel/threads/<sid> context ──
def _session(tmp_path, sid, records):
    d = tmp_path / "sessions" / "--x--"
    d.mkdir(parents=True)
    f = d / f"2026-11-05T00-00-00-000Z_{sid}.jsonl"
    f.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return f


def _cfg(tmp_path):
    c = tmp_path / "config" / "soveryn-cli"
    c.mkdir(parents=True)
    (c / "profiles.json").write_text(json.dumps({"defaultProfile": "glm", "profiles": {
        "glm": {"id": "glm", "piProviderId": "soveryn-glm", "modelId": "glm-x", "contextWindow": 123},
        "eve": {"id": "eve", "piProviderId": "soveryn-eve", "modelId": "eve", "contextWindow": 45}}}))
    (c / "pinned-runtime.json").write_text(json.dumps({"serverContextWindow": {"glm": 999}}))


def test_desk_context_from_profile_and_last_usage(tmp_path, monkeypatch):
    from soveryn.kernel_desk import manager
    _cfg(tmp_path)
    monkeypatch.setenv("SOVERYN_ROOT", str(tmp_path))
    monkeypatch.setenv("KDESK_SESSIONS_ROOT", str(tmp_path / "sessions"))
    _session(tmp_path, "s1", [
        {"type": "session", "id": "s1"},
        {"type": "model_change", "provider": "soveryn-glm", "modelId": "glm-x"},
        {"type": "message", "timestamp": "t1", "message": {"role": "assistant", "usage": {"input": 5, "cacheRead": 4, "output": 9}}},
        {"type": "message", "timestamp": "t2", "message": {"role": "assistant", "usage": {"input": 7, "cacheRead": 8, "cacheWrite": 1, "output": 3}}},
    ])
    c = manager.desk_context("s1")
    assert c["profile"] == "glm" and c["context_window"] == 123 and c["server_context_window"] == 999
    assert c["prompt_tokens"] == 16 and c["usage_at"] == "t2"


def test_desk_context_no_turn_reports_none(tmp_path, monkeypatch):
    from soveryn.kernel_desk import manager
    _cfg(tmp_path)
    monkeypatch.setenv("SOVERYN_ROOT", str(tmp_path))
    monkeypatch.setenv("KDESK_SESSIONS_ROOT", str(tmp_path / "sessions"))
    c = manager.desk_context("missing")
    assert c["context_window"] == 123 and c["prompt_tokens"] is None
