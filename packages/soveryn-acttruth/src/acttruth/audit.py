"""SOVERYN-free audit helpers: classify + ledger tool outcomes."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from acttruth.ledger import ActTruth
from acttruth.paths import default_acttruth_dir

log = logging.getLogger(__name__)

_TIMEOUT_MARKERS = (
    "timed out",
    "timeout",
    "Timeout",
    "TIMEOUT",
)


@lru_cache(maxsize=8)
def get_acttruth(root: str | None = None) -> ActTruth:
    path = Path(root).expanduser() if root else default_acttruth_dir()
    return ActTruth.open(path)


def reset_acttruth_cache() -> None:
    get_acttruth.cache_clear()


def _classify_tool_event(*, ok: bool, error: str | None, result: Any) -> tuple[str, bool, str]:
    """Return (kind, ok_flag, summary_extra). Quiet failures → timeout/tool_error."""
    err = (error or "").strip()
    # Tool handlers sometimes return {"error": ...} without raising — treat as fail.
    if ok and isinstance(result, dict) and result.get("error"):
        ok = False
        err = str(result.get("message") or result.get("error") or "tool returned error")
    if ok:
        return "tool_ok", True, ""
    blob = err
    if isinstance(result, dict):
        blob = f"{err} {result.get('error', '')} {result.get('message', '')}"
    if any(m.lower() in blob.lower() for m in _TIMEOUT_MARKERS):
        return "timeout", False, err or "timed out"
    return "tool_error", False, err or "tool failed"


def _summarize_args(args: dict) -> str:
    for key in ("prompt", "query", "message", "objective", "path", "url"):
        val = args.get(key)
        if isinstance(val, str) and val.strip():
            head = " ".join(val.split())
            return head[:120] + ("…" if len(head) > 120 else "")
    return ""


def record_tool_audit(
    *,
    agent: str,
    tool_name: str,
    args: dict,
    ok: bool,
    result: Any = None,
    error: str | None = None,
    acttruth: ActTruth | None = None,
) -> None:
    """Best-effort ledger write from a tool-call shaped outcome."""
    try:
        c = acttruth or get_acttruth()
        kind, ok_flag, detail = _classify_tool_event(ok=ok, error=error, result=result)
        arg_head = _summarize_args(dict(args or {}))
        if ok_flag:
            summary = f"{tool_name} ok"
            if arg_head:
                summary = f"{tool_name}: {arg_head}"
        else:
            summary = f"{tool_name} FAILED"
            if detail:
                summary = f"{tool_name} FAILED — {detail[:200]}"
            elif arg_head:
                summary = f"{tool_name} FAILED on: {arg_head}"
        c.ledger.record(
            agent_id=agent,
            kind=kind,  # type: ignore[arg-type]
            summary=summary,
            ok=ok_flag,
            tool=tool_name,
            tags=("quiet_failure",) if not ok_flag else (),
        )
    except Exception:
        log.exception("acttruth ledger write failed (non-fatal)")
