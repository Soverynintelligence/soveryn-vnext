"""Commit-then-return dispatch. A 'sent' id is a readable ledger row.

Pulse, ops, and Kernel have reported Forge handoffs (house_post commissions,
objective_assign, room ask_peer, dispatch_task) with an id that never landed
in data/delegation.db. This module is the single write path: the id is
returned only after the row is committed and re-read. Write failure raises
and is recorded as a ProbeRecord-shaped error for the pulse. Duplicates of
a still-live objective return the existing id (idempotent).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from soveryn.paths import SoverynPaths
from soveryn.platform.delegation.store import (
    DelegationStore,
    LedgerWriteError,
    Task,
)

logger = logging.getLogger(__name__)

FORGE_ASSIGNEES: frozenset[str] = frozenset({"forge", "kernel", "scotty"})
LIVE_STATUSES: frozenset[str] = frozenset(
    {"dispatched", "executing", "in_review", "recorded", "pending-verify"}
)
PROBE_NAME = "delegation_dispatch"
_PROBES_ENV = "SOVERYN_DISPATCH_PROBES"


@dataclass(frozen=True)
class DispatchResult:
    """A handoff that is already in the ledger. ``sent`` is always True."""

    task_id: str
    status: str
    duplicate: bool = False
    sent: bool = True
    message: str = ""

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "task_id": self.task_id,
            "status": self.status,
            "sent": True,
        }
        if self.duplicate:
            out["duplicate"] = True
        if self.message:
            out["message"] = self.message
        return out


class DispatchError(RuntimeError):
    """Ledger write failed or the row was not readable. Never claim sent."""

    def __init__(self, message: str, *, cause: BaseException | None = None) -> None:
        text = str(message)
        if "not sent" not in text:
            text = f"{text}; not sent"
        super().__init__(text)
        self.cause = cause

    def probe(self) -> dict[str, Any]:
        """Same shape as PR 1 ProbeRecord — pulse may treat this as verified."""
        return {
            "target": "delegation.db",
            "timestamp": _utc_now(),
            "result": "fail",
            "name": PROBE_NAME,
            "detail": str(self),
        }

    def as_probe_record(self) -> Any:
        raw = self.probe()
        try:
            from soveryn.platform.inference.outage import ProbeRecord

            return ProbeRecord(
                target=raw["target"],
                timestamp=raw["timestamp"],
                result=raw["result"],
                name=raw["name"],
                detail=raw["detail"],
            )
        except Exception:
            return raw


def is_forge_assignee(citizen_id: str) -> bool:
    return (citizen_id or "").strip().lower() in FORGE_ASSIGNEES


def forge_citizen_id(citizen_id: str) -> str:
    raw = (citizen_id or "").strip().lower()
    if raw in {"kernel", "scotty"}:
        return "forge"
    return raw


def default_db_path() -> Path:
    override = os.environ.get("SOVERYN_DELEGATION_DB", "").strip()
    if override:
        return Path(override)
    return SoverynPaths.data() / "delegation.db"


def default_store() -> DelegationStore:
    return DelegationStore(default_db_path())


def dispatch(
    store: DelegationStore,
    *,
    dispatched_by: str,
    objective: str,
    scope: str,
    acceptance: str,
    status: str = "dispatched",
) -> DispatchResult:
    """Write (or reuse) a ledger row. Returns the id only after it is readable."""
    existing = _find_open_duplicate(store, objective)
    if existing is not None:
        again = store.get_task(existing.id)
        if again is None:
            err = DispatchError(
                f"duplicate id {existing.id} is not readable in the ledger; not sent"
            )
            _record_probe(err.probe(), store=store)
            raise err
        return DispatchResult(
            task_id=again.id,
            status=again.status,
            duplicate=True,
            message=(
                f"Already dispatched. Task {again.id} was created at "
                f"{again.created_at} and is currently '{again.status}'. "
                "Not dispatching again. Check its status or wait for review "
                "rather than re-sending."
            ),
        )

    try:
        task_id = store.create_task(
            dispatched_by=dispatched_by,
            objective=objective,
            scope=scope,
            acceptance=acceptance,
            status=status,
        )
    except LedgerWriteError as exc:
        err = DispatchError(str(exc), cause=exc)
        _record_probe(err.probe(), store=store)
        raise err from exc
    except Exception as exc:
        err = DispatchError(
            f"delegation ledger write failed; not sent: {exc}", cause=exc
        )
        _record_probe(err.probe(), store=store)
        raise err from exc

    task = store.get_task(task_id)
    if task is None:
        err = DispatchError(
            f"delegation ledger write did not persist {task_id}; not sent"
        )
        _record_probe(err.probe(), store=store)
        raise err
    return DispatchResult(task_id=task.id, status=task.status)


def dispatch_forge_handoff(
    *,
    dispatched_by: str,
    objective: str,
    scope: str,
    acceptance: str,
    store: DelegationStore | None = None,
) -> DispatchResult:
    """Ledger-first Forge handoff (house_post / objective / room). Raises on miss."""
    st = store if store is not None else default_store()
    return dispatch(
        st,
        dispatched_by=dispatched_by,
        objective=objective,
        scope=scope,
        acceptance=acceptance,
        status="recorded",
    )


def recent_dispatch_probes(
    *,
    limit: int = 8,
    path: Path | None = None,
) -> tuple[dict[str, Any], ...]:
    """Recent persist-or-raise probes (fail rows) for the pulse."""
    probe_path = path or _probe_path()
    if not probe_path.is_file():
        return ()
    try:
        lines = probe_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ()
    rows: list[dict[str, Any]] = []
    for line in lines[-max(1, limit) * 4 :]:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("result") == "fail":
            rows.append(row)
    return tuple(rows[-limit:])


def format_dispatch_error_block(*, limit: int = 8) -> str:
    """Heartbeat prompt block. Empty when nothing probed-failing."""
    downs = recent_dispatch_probes(limit=limit)
    if not downs:
        return ""
    lines = ["## Verified dispatch failures (same-store probe records)"]
    for row in downs:
        lines.append(
            f"- {row.get('name') or 'delegation_dispatch'}: result={row.get('result')} "
            f"target={row.get('target')} timestamp={row.get('timestamp')}"
            + (f" ({row.get('detail')})" if row.get("detail") else "")
        )
    lines.append(
        "These are code-gathered probe records. Do not claim the matching "
        "handoff was sent. Do not invent a task id."
    )
    return "\n".join(lines) + "\n\n"


def as_probe_records(probes: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> list[Any]:
    """PR 1 ProbeRecord when that module exists; otherwise the raw dicts."""
    out: list[Any] = []
    ProbeRecord = None
    try:
        from soveryn.platform.inference.outage import ProbeRecord as _PR

        ProbeRecord = _PR
    except Exception:
        ProbeRecord = None
    for raw in probes:
        if ProbeRecord is None:
            out.append(raw)
            continue
        try:
            out.append(
                ProbeRecord(
                    target=str(raw.get("target") or "delegation.db"),
                    timestamp=str(raw.get("timestamp") or _utc_now()),
                    result=str(raw.get("result") or "fail"),
                    name=str(raw.get("name") or PROBE_NAME),
                    detail=str(raw.get("detail") or ""),
                )
            )
        except Exception:
            out.append(raw)
    return out


def _find_open_duplicate(store: DelegationStore, objective: str) -> Task | None:
    def norm(text: str) -> str:
        return " ".join((text or "").split()).casefold()

    target = norm(objective)
    try:
        for task in store.list_tasks():
            if task.status in LIVE_STATUSES and norm(task.objective) == target:
                return task
    except Exception:
        return None
    return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _probe_path() -> Path:
    override = os.environ.get(_PROBES_ENV, "").strip()
    if override:
        return Path(override)
    return SoverynPaths.data() / "dispatch_probes.jsonl"


def _record_probe(probe: dict[str, Any], *, store: DelegationStore | None) -> None:
    path = _probe_path()
    if store is not None and not os.environ.get(_PROBES_ENV, "").strip():
        path = store.db_path.parent / "dispatch_probes.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(probe, default=str) + "\n")
    except Exception:
        logger.warning("dispatch probe persist failed", exc_info=True)
