"""32K lean-tail: turn-reaper, fat-tool spill, old-assistant cap.

Hermes steal (mechanisms, not their compressor LLM):
- Recency window stays verbatim; older bulk is disposable.
- Fat tool results spill to disk with a recovery pointer.
- History drops whole turns (user + follow-on), never orphan messages.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Sequence

from soveryn.platform.inference.llama_server_client import ChatMessage

# Spill when a tool body is bigger than this (~2k tokens). Head+tail stay in
# the prompt so Kernel usually does not need to re-read.
SPILL_TRIGGER_CHARS = 8_000
SPILL_HEAD_CHARS = 2_400
SPILL_TAIL_CHARS = 800

# After reaping, remaining older assistant bodies over this get capped so a
# kept-but-not-latest turn cannot sit on 6k of patch dump.
LEAN_ASSISTANT_CHARS = 4_000
_CAP_NOTE = "\n[…older reply capped for 32k window…]"

_SPILL_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _data_root(data_root: Path | None = None) -> Path:
    if data_root is not None:
        return Path(data_root)
    raw = os.environ.get("SOVERYN_DATA_ROOT")
    if raw:
        return Path(raw)
    from soveryn.config.loader import DEFAULT_DATA_ROOT

    return Path(DEFAULT_DATA_ROOT)


def spill_dir(data_root: Path | None = None) -> Path:
    return _data_root(data_root) / "tool_spill"


def _safe_id(value: str, fallback: str) -> str:
    cleaned = _SPILL_ID_RE.sub("_", (value or "").strip())[:80]
    return cleaned or fallback


def maybe_spill_tool_content(
    content: str,
    *,
    tool_name: str,
    call_id: str,
    session_id: str | None = None,
    data_root: Path | None = None,
) -> str:
    """If ``content`` is fat, write the full body and return a head/tail stub.

    Small bodies pass through unchanged (byte-identical, cache-safe).
    Write failures return the original body — the in-turn fitter still truncates.
    """
    text = str(content or "")
    if len(text) <= SPILL_TRIGGER_CHARS:
        return text
    sid = _safe_id(session_id or "anon", "anon")
    cid = _safe_id(call_id or "tool", "tool")
    name = _safe_id(tool_name or "tool", "tool")
    dest_dir = spill_dir(data_root) / sid
    path = dest_dir / f"{cid}.txt"
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError:
        return text
    rel = path.as_posix()
    try:
        rel = str(path.relative_to(_data_root(data_root).parent))
    except ValueError:
        rel = path.as_posix()
    omitted = len(text) - SPILL_HEAD_CHARS - SPILL_TAIL_CHARS
    marker = (
        f"\n\n[{name} output {len(text)} chars — middle {max(0, omitted)} "
        f"spilled to {rel}. read_file that path if you need the rest.]\n\n"
    )
    return text[:SPILL_HEAD_CHARS] + marker + text[-SPILL_TAIL_CHARS:]


def group_turns(
    history: Sequence[ChatMessage],
) -> list[tuple[ChatMessage, ...]]:
    """Split history into turns. A turn starts at each user message.

    Leading non-user messages (orphan assistant) form their own first turn.
    """
    turns: list[list[ChatMessage]] = []
    for msg in history:
        if msg.role == "user" or not turns:
            turns.append([msg])
        else:
            turns[-1].append(msg)
    return [tuple(t) for t in turns]


def _cap_assistant(msg: ChatMessage) -> ChatMessage:
    if msg.role not in {"assistant", "tool"}:
        return msg
    if not isinstance(msg.content, str):
        return msg
    if len(msg.content) <= LEAN_ASSISTANT_CHARS:
        return msg
    keep = max(0, LEAN_ASSISTANT_CHARS - len(_CAP_NOTE))
    return ChatMessage(
        role=msg.role,
        content=msg.content[:keep] + _CAP_NOTE,
        tool_call_id=msg.tool_call_id,
        tool_calls=msg.tool_calls,
    )


def reap_history(
    prelude: Sequence[ChatMessage],
    history: Sequence[ChatMessage],
    budget: int,
    *,
    charge_prelude: bool = False,
    estimate_fn=None,
) -> tuple[tuple[ChatMessage, ...], ChatMessage | None, int]:
    """Drop oldest complete turns until history fits ``budget``.

    Always keeps the last turn. If remaining older assistant bodies still
    blow the budget, cap them (user words stay verbatim). Returns
    (kept_history, elision_marker_or_None, elided_turn_count).
    """
    if not history:
        return tuple(history), None, 0
    if estimate_fn is None:
        from soveryn.agents.loop import _estimate_message_tokens as estimate_fn

    def tokens(msgs: Sequence[ChatMessage]) -> int:
        return sum(estimate_fn(m) for m in msgs)

    prelude_tokens = tokens(prelude) if charge_prelude else 0

    def charged(turns: list[tuple[ChatMessage, ...]]) -> int:
        flat = [m for t in turns for m in t]
        return prelude_tokens + tokens(flat)

    turns = group_turns(history)
    if charged(turns) <= budget:
        return tuple(history), None, 0

    # Lean-tail first: shrink older assistant/tool bodies so user questions
    # can stay. Then reap whole turns if still over.
    capped = False
    if len(turns) > 1:
        capped_turns = [
            turn if i == len(turns) - 1 else tuple(_cap_assistant(m) for m in turn)
            for i, turn in enumerate(turns)
        ]
        if charged(capped_turns) < charged(turns):
            turns = capped_turns
            capped = True
            if charged(turns) <= budget:
                kept = tuple(m for t in turns for m in t)
                marker = ChatMessage(
                    role="system",
                    content="[Context: older assistant bodies capped to fit token budget.]",
                )
                return kept, marker, 0

    dropped = 0
    while len(turns) > 1 and charged(turns) > budget:
        turns.pop(0)
        dropped += 1

    kept = tuple(m for t in turns for m in t)
    if dropped == 0 and not capped:
        return tuple(history), None, 0
    if dropped == 0:
        marker = ChatMessage(
            role="system",
            content="[Context: older assistant bodies capped to fit token budget.]",
        )
        return kept, marker, 0
    marker = ChatMessage(
        role="system",
        content=f"[Context: {dropped} older turn(s) elided to fit token budget.]",
    )
    return kept, marker, dropped
