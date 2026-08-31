"""Parity: message_thread.html attach enumerations match vision_types.

chat.html is covered by test_vision_types_parity.py. The phone door
(`/messages/<agent>`) is a separate static file and must stay in sync
the same way — accept attribute, MIME set, and ATTACH_CAPABLE_AGENTS.
"""

from __future__ import annotations

import re
from pathlib import Path

from soveryn.platform.vision_types import (
    ACCEPT_ATTRIBUTE_VALUE,
    ALLOWED_IMAGE_MIMES,
    VISION_CAPABLE_AGENTS,
)


THREAD_HTML = (
    Path(__file__).resolve().parents[1]
    / "soveryn" / "app" / "templates" / "message_thread.html"
)


def _read() -> str:
    return THREAD_HTML.read_text(encoding="utf-8")


def _js_set(html: str, name: str) -> frozenset[str]:
    match = re.search(rf"{name}\s*=\s*new\s+Set\(\s*\[([^\]]+)\]", html)
    assert match is not None, f"no {name} Set literal found in message_thread.html"
    return frozenset(m.group(1) for m in re.finditer(r'"([^"]+)"', match.group(1)))


def test_message_thread_accept_attribute_matches_canonical():
    html = _read()
    match = re.search(r'accept="([^"]+)"', html)
    assert match is not None, "no accept= attribute found in message_thread.html"
    assert match.group(1) == ACCEPT_ATTRIBUTE_VALUE


def test_message_thread_allowed_image_mimes_set_matches_canonical():
    assert _js_set(_read(), "ALLOWED_IMAGE_MIMES") == ALLOWED_IMAGE_MIMES


def test_message_thread_attach_capable_agents_match_canonical():
    """Image gate only — paperclip itself is on every Messages chat seat."""
    assert _js_set(_read(), "ATTACH_CAPABLE_AGENTS") == VISION_CAPABLE_AGENTS


def test_message_thread_has_paperclip_capture_and_posts_attachments():
    html = _read()
    assert 'data-attach' in html
    assert 'data-file-input' in html
    assert 'data-composer-attachments' in html
    assert re.search(r"\bcapture=", html)
    assert re.search(r"body\.attachments\s*=", html)
    assert '"(image)"' in html


def test_vision_capable_agents_include_eve_not_kernel_or_qwen38_peers():
    assert VISION_CAPABLE_AGENTS == frozenset(
        {"aetheria", "vett", "scotty", "eve"}
    )
    for name in ("kernel", "grok", "pondwright", "seneca", "atticus", "cognition"):
        assert name not in VISION_CAPABLE_AGENTS
