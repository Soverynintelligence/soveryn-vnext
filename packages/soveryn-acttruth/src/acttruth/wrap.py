"""Wrap any callable so outcomes land on the ActTruth ledger.

Soft lessons only (v0): after a FAIL streak, the wrapper can attach an
``acttruth_lesson`` string on dict results or raise nothing — never hard-blocks.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, TypeVar

from acttruth.audit import record_tool_audit
from acttruth.ledger import ActTruth
from acttruth.lessons import maybe_lesson_for_tool_result

F = TypeVar("F", bound=Callable[..., Any])


def wrap_callable(
    fn: Callable[..., Any],
    *,
    agent: str,
    tool_name: str | None = None,
    acttruth: ActTruth | None = None,
    attach_lesson: bool = True,
) -> Callable[..., Any]:
    """Return a wrapper that ledgers OK / FAIL / timeout for ``fn``."""
    name = tool_name or getattr(fn, "__name__", "tool")

    @functools.wraps(fn)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        call_args = dict(kwargs)
        if args:
            call_args["_args"] = repr(args)[:200]
        try:
            result = fn(*args, **kwargs)
        except Exception as exc:
            record_tool_audit(
                agent=agent,
                tool_name=name,
                args=call_args,
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
                acttruth=acttruth,
            )
            if attach_lesson:
                maybe_lesson_for_tool_result(
                    agent,
                    tool=name,
                    ok=False,
                    error=str(exc),
                )
            raise

        soft_fail = isinstance(result, dict) and bool(result.get("error"))
        record_tool_audit(
            agent=agent,
            tool_name=name,
            args=call_args,
            ok=not soft_fail,
            result=result,
            error=str(result.get("error")) if soft_fail else None,
            acttruth=acttruth,
        )
        if attach_lesson and soft_fail and isinstance(result, dict):
            lesson = maybe_lesson_for_tool_result(
                agent,
                tool=name,
                ok=False,
                result=result,
            )
            if lesson:
                # Non-destructive: add lesson beside the error payload.
                out = dict(result)
                out.setdefault("acttruth_lesson", lesson)
                return out
        return result

    return wrapped


def audit_tool(
    *,
    agent: str,
    name: str | None = None,
    acttruth: ActTruth | None = None,
    attach_lesson: bool = True,
) -> Callable[[F], F]:
    """Decorator: ``@audit_tool(agent="demo", name="search")``."""

    def deco(fn: F) -> F:
        return wrap_callable(  # type: ignore[return-value]
            fn,
            agent=agent,
            tool_name=name,
            acttruth=acttruth,
            attach_lesson=attach_lesson,
        )

    return deco
