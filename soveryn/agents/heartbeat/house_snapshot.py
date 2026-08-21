"""House-work snapshot for heartbeat delta (best-effort, no raises).

Widens “something moved” beyond board/lattice so Aetheria can wake for
automations Results, Approval Gate, ActTruth triage, and Active-now /
on-duty citizens — not only coord board churn.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def gather_house_snapshot(
    *,
    data_root: Path | None = None,
    citizens_db: Path | str | None = None,
    conv_db: Path | str | None = None,
) -> dict[str, Any]:
    """Return the ``house`` block for ``current_snapshot``.

    Shape::

        {
            "automations_unread_count": int,
            "automations_inbox_latest_id": str | None,
            "gate_pending_count": int,
            "triage_open_count": int,
            "on_duty_count": int,
            "active_now_count": int,
        }
    """
    root = Path(data_root) if data_root is not None else None
    return {
        "automations_unread_count": _automations_unread(root),
        "automations_inbox_latest_id": _automations_latest_id(root),
        "gate_pending_count": _gate_pending(root),
        "triage_open_count": _triage_open(root),
        "on_duty_count": _on_duty_count(citizens_db),
        "active_now_count": _active_now_count(citizens_db, conv_db),
    }


def _automations_unread(data_root: Path | None) -> int:
    try:
        from soveryn.automations.inbox import list_inbox

        rows = list_inbox(limit=80, data_root=data_root)
        return sum(1 for r in rows if not r.get("read"))
    except Exception:
        logger.debug("house snapshot: automations inbox unreadable", exc_info=True)
        return 0


def _automations_latest_id(data_root: Path | None) -> str | None:
    try:
        from soveryn.automations.inbox import list_inbox

        rows = list_inbox(limit=1, data_root=data_root)
        if not rows:
            return None
        rid = rows[0].get("id") or rows[0].get("run_id")
        return str(rid) if rid else None
    except Exception:
        logger.debug("house snapshot: automations latest id failed", exc_info=True)
        return None


def _gate_pending(data_root: Path | None) -> int:
    try:
        from soveryn.platform.approval.store import ApprovalStore

        if data_root is not None:
            db = Path(data_root) / "memory" / "approvals.db"
        else:
            from soveryn.config.loader import DEFAULT_DATA_ROOT

            db = Path(DEFAULT_DATA_ROOT) / "memory" / "approvals.db"
        if not db.exists():
            return 0
        return len(ApprovalStore(db).pending_all())
    except Exception:
        logger.debug("house snapshot: approval gate unreadable", exc_info=True)
        return 0


def _triage_open(data_root: Path | None) -> int:
    try:
        from soveryn.platform.acttruth.triage import list_triage

        return len(list_triage(limit=80, status="open", data_root=data_root))
    except Exception:
        logger.debug("house snapshot: triage unreadable", exc_info=True)
        return 0


def _on_duty_count(citizens_db: Path | str | None) -> int:
    if citizens_db is None:
        return 0
    path = Path(citizens_db)
    if not path.exists():
        return 0
    try:
        with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=2.0) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM commissions WHERE state = 'running'"
            ).fetchone()
            return int(row[0]) if row else 0
    except Exception:
        logger.debug("house snapshot: on_duty count failed", exc_info=True)
        return 0


def _active_now_count(
    citizens_db: Path | str | None,
    conv_db: Path | str | None,
) -> int:
    try:
        from soveryn.citizens.active_now import build_active_now

        out = build_active_now(citizens_db, conv_db)
        return int(out.get("count") or 0)
    except Exception:
        logger.debug("house snapshot: active_now failed", exc_info=True)
        return 0
