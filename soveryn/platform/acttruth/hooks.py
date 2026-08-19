"""SOVERYN wiring helpers — compose ActTruth audit with house telemetry."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from acttruth.audit import record_tool_audit as _record_tool_audit
from acttruth.audit import reset_acttruth_cache as _reset_pkg_cache
from acttruth.ledger import ActTruth

from soveryn.platform.acttruth.paths import default_acttruth_dir

log = logging.getLogger(__name__)


@lru_cache(maxsize=4)
def get_acttruth(root: str | None = None) -> ActTruth:
    path = Path(root) if root else default_acttruth_dir()
    return ActTruth.open(path)


def reset_acttruth_cache() -> None:
    get_acttruth.cache_clear()
    _reset_pkg_cache()


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
    """Best-effort ledger write — delegates to portable acttruth.audit."""
    _record_tool_audit(
        agent=agent,
        tool_name=tool_name,
        args=args,
        ok=ok,
        result=result,
        error=error,
        acttruth=acttruth or get_acttruth(),
    )


def acttruth_and_telemetry_audit_hook(event: Any) -> None:
    """Compose ActTruth + existing telemetry so quiet failures cannot slip by."""
    from soveryn.platform.tools.registry import telemetry_audit_hook

    try:
        record_tool_audit(
            agent=event.agent,
            tool_name=event.tool_name,
            args=dict(event.args or {}),
            ok=bool(event.ok),
            result=getattr(event, "result", None),
            error=getattr(event, "error", None),
        )
    except Exception:
        log.exception("acttruth audit hook failed")
    telemetry_audit_hook(event)
