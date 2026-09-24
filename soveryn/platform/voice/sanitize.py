"""Sanitize assistant text for TTS at source.

Single function, single boundary. Replaces the accumulated filter chain
from the legacy voice pipeline (project_soveryn_voice_pipeline.md notes
the chain that grew over months of patches)."""

from __future__ import annotations
import re
import unicodedata


# Compiled once for performance.
#
# _RE_THINK_TAG matches an innermost <think>...</think> pair (the negative
# lookahead on `<think\b` blocks consuming a nested opener). Applied in a
# loop so nested tags are stripped from the inside out. After the loop
# stabilizes, _RE_THINK_TAG_UNCLOSED drops any opener that never closed.
_RE_THINK_TAG = re.compile(
    r"<think\b[^>]*>(?:(?!<think\b).)*?</think>",
    re.DOTALL | re.IGNORECASE,
)
_RE_THINK_TAG_UNCLOSED = re.compile(r"<think\b[^>]*>.*$", re.DOTALL | re.IGNORECASE)
_RE_TOOL_CALL = re.compile(r"<tool_call\b[^>]*>.*?</tool_call>", re.DOTALL | re.IGNORECASE)
_RE_BRACKET_TAG = re.compile(
    r"\[(SCRATCHPAD|RESOLVE|DEFER|HEARTBEAT|TOOL|SYSTEM)[^\]]*\]\s*\n?",
    re.IGNORECASE,
)
_RE_CONTROL_TOKEN = re.compile(r"<\|[^|]*\|>")
_RE_WHITESPACE = re.compile(r"\s+")
# Unwrap **bold** / *italic*, then drop leftover asterisks so F5
# does not speak "asterisk".
_RE_MD_EMPHASIS = re.compile(r"\*{1,2}([^*]+)\*{1,2}")


def sanitize_for_tts(text: str, *, preserve_outer_whitespace: bool = False) -> str:
    """Strip thinking markup, control tokens, tool-call JSON, scratchpad
    tags, emoji, and markdown * / ** from `text`. Return clean prose for TTS.

    When ``preserve_outer_whitespace`` is True, keep leading/trailing
    whitespace boundaries after sanitization. This is for chunked TTS
    streams, where token edges need to survive so adjacent chunks don't
    glue words together. Empty / whitespace-only input still returns
    ``""``.

    Idempotent. Empty input → empty output. Preserves sentence-ending
    punctuation (matters for TTS prosody)."""
    if not text:
        return ""
    # Strip nested <think>...</think> from the inside out, then drop any
    # unclosed opener (everything from the orphan opener to EOF).
    while True:
        new_text = _RE_THINK_TAG.sub("", text)
        if new_text == text:
            break
        text = new_text
    text = _RE_THINK_TAG_UNCLOSED.sub("", text)
    text = _RE_TOOL_CALL.sub("", text)
    text = _RE_BRACKET_TAG.sub("", text)
    text = _RE_CONTROL_TOKEN.sub("", text)
    text = _RE_MD_EMPHASIS.sub(r"\1", text)
    text = text.replace("*", "")
    text = "".join(c for c in text if unicodedata.category(c)[0] != "S")
    text = _RE_WHITESPACE.sub(" ", text)
    if preserve_outer_whitespace:
        return "" if not text.strip() else text
    text = text.strip()
    return text
