"""Thin helpers for OpenAI-compatible tool-call loops.

No OpenAI SDK dependency. Pass tool name / args / result (or exception)
after each tool execution; optionally prepend a lessons brief into messages.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableSequence
from typing import Any

from acttruth.audit import record_tool_audit
from acttruth.ledger import ActTruth
from acttruth.lessons import lessons_brief, maybe_lesson_for_tool_result


def record_openai_tool_result(
    *,
    agent: str,
    tool_name: str,
    arguments: Mapping[str, Any] | str | None = None,
    result: Any = None,
    error: str | None = None,
    ok: bool | None = None,
    acttruth: ActTruth | None = None,
    attach_lesson: bool = True,
) -> str | None:
    """Ledger one tool outcome from a Chat Completions-style loop.

    Returns an optional soft lesson string when a FAIL streak is armed.
    """
    if isinstance(arguments, str):
        args: dict[str, Any] = {"raw": arguments[:500]}
    else:
        args = dict(arguments or {})

    if ok is None:
        if error:
            ok = False
        elif isinstance(result, dict) and result.get("error"):
            ok = False
        else:
            ok = True

    record_tool_audit(
        agent=agent,
        tool_name=tool_name,
        args=args,
        ok=ok,
        result=result,
        error=error,
        acttruth=acttruth,
    )
    if not attach_lesson or ok:
        return None
    return maybe_lesson_for_tool_result(
        agent,
        tool=tool_name,
        ok=False,
        error=error,
        result=result,
    )


def wrap_tool_dispatch(
    tools: Mapping[str, Callable[..., Any]],
    *,
    agent: str,
    acttruth: ActTruth | None = None,
) -> dict[str, Callable[..., Any]]:
    """Wrap a name→callable tool map with ActTruth auditing."""
    from acttruth.wrap import wrap_callable

    return {
        name: wrap_callable(fn, agent=agent, tool_name=name, acttruth=acttruth)
        for name, fn in tools.items()
    }


def inject_lessons_message(
    messages: MutableSequence[dict[str, Any]],
    agent: str,
    *,
    role: str = "system",
) -> bool:
    """Prepend/refresh an ActTruth lessons brief as a message. Returns True if added."""
    brief = lessons_brief(agent)
    if not brief.strip():
        return False
    block = {
        "role": role,
        "content": brief,
    }
    # Replace prior ActTruth lesson system message if present.
    for i, msg in enumerate(list(messages)):
        content = str(msg.get("content") or "")
        if "ACTTRUTH LESSONS" in content or "ACTTRUTH — what actually happened" in content:
            messages[i] = block
            return True
    messages.insert(0, block)
    return True
