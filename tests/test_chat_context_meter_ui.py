"""revamp phase 3: chat.html context meter reads the server-reported limit (static check)."""
from pathlib import Path

HTML = (Path(__file__).resolve().parents[1] / "soveryn/app/templates/chat.html").read_text()


def test_meter_element_and_hook():
    assert 'data-testid="context-meter"' in HTML
    i = HTML.index("function updateContextUsage(usage) {")
    assert "updateContextMeter(usage);" in HTML[i:i + 120]


def test_meter_never_hardcodes_a_limit():
    import re
    start = HTML.index("function updateContextMeter")
    body = HTML[start:HTML.index("function updateContextUsage", start)]
    code = "\n".join(l for l in body.splitlines() if not l.strip().startswith("//"))
    assert "usage.context_window" in code
    assert not re.search(r"\b\d{4,}\b", code.replace(",", "")), "hardcoded number in meter code"
    assert "innerHTML" not in code
