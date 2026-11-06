"""revamp phase 2: chat.html renders turn_tool_calls safely (static check)."""
from pathlib import Path

HTML = (Path(__file__).resolve().parents[1] / "soveryn/app/templates/chat.html").read_text()


def test_sync_path_renders_turn_tool_calls():
    assert "renderTurnTools(respBubble, data.turn_tool_calls)" in HTML


def test_turn_tools_uses_textcontent_not_innerhtml():
    start = HTML.index("function renderTurnTools")
    body = HTML[start:HTML.index("function appendBubble", start)]
    assert "innerHTML" not in body and "textContent" in body
