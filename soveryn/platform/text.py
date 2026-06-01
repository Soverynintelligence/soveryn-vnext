"""Shared text utilities. Currently: think-block markup stripping.

Lives in the platform layer because it's pure-text manipulation with no
dependencies on inference, memory, or any agent — multiple callers across
domain layers need the same behavior. Extracted 2026-05-31 from the
duplicate copies that grew in llama_server_client.py (strip at inference
boundary) and conversation_store.py (strip on history load).

When the model emits reasoning markup that the chat template doesn't fully
fence, the four patterns here clean it up at any seam:

  1. <think>...</think>             paired block (canonical case)
  2. <think>...EOF                  open tag with no close (cap saturation,
                                    truncation, or stream cut mid-think)
  3. naked reasoning + lone </think>
                                    model streamed reasoning prose with no
                                    opening tag, then closed it — leaves
                                    nothing visible above the </think>
  4. lone </think>                  bare close-tag backstop
"""

from __future__ import annotations

import re


_THINK_BLOCK_RE = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)
_THINK_OPEN_RE = re.compile(r"<think>[\s\S]*", re.IGNORECASE)
_THINK_NAKED_RE = re.compile(
    r"\A(?:(?!<think>).)*?</think>\s*", re.IGNORECASE | re.DOTALL,
)
_THINK_CLOSE_RE = re.compile(r"</think>", re.IGNORECASE)


def strip_think_markup(text: str) -> str:
    """Remove all four shapes of <think> markup from visible content."""
    if not text:
        return text
    cleaned = _THINK_BLOCK_RE.sub("", text)
    cleaned = _THINK_OPEN_RE.sub("", cleaned)
    cleaned = _THINK_NAKED_RE.sub("", cleaned)
    cleaned = _THINK_CLOSE_RE.sub("", cleaned)
    return cleaned
