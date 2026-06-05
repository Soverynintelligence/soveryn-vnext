"""Parity tests: the chat.html composer's image-MIME enumerations must
match soveryn.platform.vision_types.

The HTML carries two literal enumerations (the file-input `accept`
attribute + the JS `ALLOWED_IMAGE_MIMES` Set) that can't import the Python
const directly. These tests assert they stay in sync — if you add a MIME
to vision_types, this test fails until you update the HTML too.
"""

from __future__ import annotations

import re
from pathlib import Path

from soveryn.platform.vision_types import (
    ACCEPT_ATTRIBUTE_VALUE,
    ALLOWED_IMAGE_MIMES,
)


CHAT_HTML = Path(__file__).resolve().parents[1] / "soveryn" / "app" / "templates" / "chat.html"


def _read_chat_html() -> str:
    return CHAT_HTML.read_text(encoding="utf-8")


def test_chat_html_accept_attribute_matches_canonical():
    """The file-input's `accept=` value must equal ACCEPT_ATTRIBUTE_VALUE."""
    html = _read_chat_html()
    match = re.search(r'accept="([^"]+)"', html)
    assert match is not None, "no accept= attribute found in chat.html"
    found = match.group(1)
    assert found == ACCEPT_ATTRIBUTE_VALUE, (
        f"chat.html `accept` drifted from vision_types.\n"
        f"  HTML:   {found!r}\n"
        f"  Canon:  {ACCEPT_ATTRIBUTE_VALUE!r}"
    )


def test_chat_html_allowed_image_mimes_set_matches_canonical():
    """The JS ALLOWED_IMAGE_MIMES = new Set([...]) must equal the canonical
    frozenset (order-independent)."""
    html = _read_chat_html()
    match = re.search(
        r"ALLOWED_IMAGE_MIMES\s*=\s*new\s+Set\(\s*\[([^\]]+)\]",
        html,
    )
    assert match is not None, "no ALLOWED_IMAGE_MIMES Set literal found in chat.html"
    raw = match.group(1)
    found = frozenset(
        m.group(1) for m in re.finditer(r'"([^"]+)"', raw)
    )
    assert found == ALLOWED_IMAGE_MIMES, (
        f"chat.html ALLOWED_IMAGE_MIMES drifted from vision_types.\n"
        f"  HTML:   {sorted(found)}\n"
        f"  Canon:  {sorted(ALLOWED_IMAGE_MIMES)}"
    )
