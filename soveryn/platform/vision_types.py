"""Single source of truth for accepted vision-image types.

Three surfaces enumerate the same set independently:
  - /chat + /chat_stream route validator (data: URL prefix check)
  - signal_bridge daemon inbound encoder (file extension → MIME)
  - chat.html composer file-input `accept` + JS MIME set

This module owns the canonical list. The route and daemon import from
here; the UI's HTML strings are verified to match by
tests/test_vision_types_html_parity.py.

To add a new image type: add the MIME here, update the HTML literally
(the parity test will fail until you do), and confirm the model's mmproj
actually decodes it.
"""

from __future__ import annotations


# Canonical (mime, file-extension) pairs. Ordered by descending UI prevalence
# so the UI's `accept` attribute matches client-side OS file-picker behavior
# (jpeg shows first in dropdowns).
IMAGE_TYPES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("image/jpeg", (".jpg", ".jpeg")),
    ("image/png",  (".png",)),
    ("image/webp", (".webp",)),
    ("image/gif",  (".gif",)),
)

# Set of accepted MIMEs (UI Set, daemon reverse-lookup target).
ALLOWED_IMAGE_MIMES: frozenset[str] = frozenset(mime for mime, _ in IMAGE_TYPES)

# Prefix-form for the route's `startswith` check on data: URLs.
ALLOWED_IMAGE_MIME_PREFIXES: tuple[str, ...] = tuple(
    f"data:{mime}" for mime, _ in IMAGE_TYPES
)

# Reverse-lookup ext → MIME for the bridge encoder.
IMAGE_EXT_TO_MIME: dict[str, str] = {
    ext: mime
    for mime, exts in IMAGE_TYPES
    for ext in exts
}

# Comma-separated `accept` attribute value for the UI file input.
ACCEPT_ATTRIBUTE_VALUE: str = ",".join(mime for mime, _ in IMAGE_TYPES)


# Agents whose serving profile loads an mmproj vision projector — i.e. the
# agents that can actually decode an image attachment. Aetheria runs on her
# own vision-enabled server; Vett and Scotty share the `vett-scotty`
# llama-server, which loads `mmproj-Qwen_Qwen3.6-27B-bf16.gguf`
# (see runtime/router-presets.ini). Any agent NOT in this set has no
# projector loaded and must have image attachments rejected.
#
# Single source of truth: the /chat route gate and the AgentLoop vision guard
# import this set, and the UI's JS `ATTACH_CAPABLE_AGENTS` Set mirrors it
# (chat.html is served as a static file, so it can't import Python directly;
# the const is named ATTACH_CAPABLE_AGENTS rather than VISION_* only because
# the served page is scanned for the retired 'Vision' agent name) — the
# mirror is guarded by tests/test_vision_types_parity.py.
VISION_CAPABLE_AGENTS: frozenset[str] = frozenset({"aetheria", "vett", "scotty"})
