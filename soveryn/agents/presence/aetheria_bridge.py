"""Bridges presence drafting to Aetheria's real AgentLoop.

`make_draft_fn` returns a `Callable[[str], str]` suitable for injection into
`draft_for_candidate` (soveryn/agents/presence/drafting.py). Each call opens
a fresh `[presence]`-titled session and runs one turn through the real
`AgentLoop.process_message`.

Two failure modes are converted into a silent-skip JSON literal rather than
propagated or returned as broken content:
  - `finish_reason == "tool_round_limit"` — the turn was cut off exhausted.
  - empty/whitespace-only content — nothing to post.

Real models frequently wrap JSON replies in a markdown code fence
(``` ```json ... ``` ```). `draft_for_candidate`'s parser is a strict
`json.loads`, so a fenced reply would silently vanish as a skip downstream.
This module strips a leading/trailing fence before returning so the string
handed to the parser is clean JSON.
"""

from __future__ import annotations

import re
from typing import Callable

SKIP_LITERAL = '{"skip":true,"post":"","based_on":""}'

_FENCE_RE = re.compile(
    r"^```(?:json)?\s*\n?(.*?)\n?```$",
    re.DOTALL,
)


def _strip_code_fence(text: str) -> str:
    """Strip a leading/trailing ``` or ```json fence and surrounding whitespace."""
    stripped = text.strip()
    match = _FENCE_RE.match(stripped)
    if match:
        return match.group(1).strip()
    return stripped


def make_draft_fn(loop, conv_store) -> Callable[[str], str]:
    """Return a draft_fn that runs `prompt` through Aetheria's AgentLoop.

    loop — an AgentLoop (or duck-typed equivalent) with
      `process_message(session_id, user_message) -> ChatResponse`.
    conv_store — a ConversationStore (or duck-typed equivalent) with
      `new_session(agent, title=None) -> session_id`.
    """

    def draft_fn(prompt: str) -> str:
        session_id = conv_store.new_session("aetheria", title="[presence] draft")
        resp = loop.process_message(session_id, prompt)

        if resp.finish_reason == "tool_round_limit" or not resp.content.strip():
            return SKIP_LITERAL

        return _strip_code_fence(resp.content)

    return draft_fn
