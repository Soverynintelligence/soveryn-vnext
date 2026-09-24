"""Seed standing desk objectives so autonomy does not die when one-shots finish.

Called from census. Idempotent: only creates when a desk has no active /
ready_for_verify / blocked work. Enqueues the research/commission body so
workers can pick it up without Jon poking.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from soveryn.citizens import commissions
from soveryn.citizens import objectives as objectives_mod

logger = logging.getLogger("soveryn.citizens.standing_work")

_OPEN = frozenset({"active", "ready_for_verify", "blocked"})

# Stable briefs — keep titles stable-ish so humans recognize the standing jobs.
STANDING: tuple[dict[str, Any], ...] = (
    {
        "desk": "soveryn",
        "owner_id": "kernel",
        "title": "Standing · house improvement queue",
        "brief": (
            "Standing SOVERYN improvement objective. Review recent house reality "
            "(citizen autonomy gaps, Flash/Kernel speed, Messages UX, PondWright, "
            "spine debt) and pick the single highest-leverage bounded fix or "
            "design note for this cycle. Deliver something Jon can verify — a "
            "patch, a clear design, or an honest blocked with next ask. Do not "
            "wait for another chat prompt."
        ),
        "success_criteria": (
            "One concrete improvement shipped or a design/blocked note with "
            "receipts ready for Jon verify"
        ),
    },
    # CWG pricing watch was minting a ready_for_verify brief into Jon's DM
    # on a loop. He did not ask for it and cancelled 2026-09-01. Do not
    # re-seed. Quote/catalog work is on-demand via PondWright tools.
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def desk_has_open_work(conn, desk: str) -> bool:
    rows = objectives_mod.list_objectives(conn, desk=desk, limit=20)
    return any((r.get("state") or "") in _OPEN for r in rows)


def ensure_standing_objectives(conn) -> list[dict[str, Any]]:
    """Create missing standing objectives and enqueue work. Returns created rows."""
    created: list[dict[str, Any]] = []
    at = _now()
    for spec in STANDING:
        desk = spec["desk"]
        if desk_has_open_work(conn, desk):
            continue
        # Citizen must exist (FK)
        exists = conn.execute(
            "SELECT 1 FROM citizens WHERE id = ?", (spec["owner_id"],)
        ).fetchone()
        if exists is None:
            logger.warning(
                "skip standing %s — citizen %s missing",
                desk,
                spec["owner_id"],
            )
            continue
        row = objectives_mod.assign(
            conn,
            desk=desk,
            title=spec["title"],
            brief=spec["brief"],
            at=at,
            owner_id=spec["owner_id"],
            success_criteria=spec["success_criteria"],
            assigned_by="standing_work",
        )
        cid = commissions.enqueue(
            conn,
            row["owner_id"],
            objectives_mod.commission_body_for(row),
            at=at,
        )
        logger.info(
            "seeded standing objective %s desk=%s owner=%s commission=%s",
            row["id"][:8],
            desk,
            row["owner_id"],
            cid,
        )
        created.append({**row, "commission_id": cid})
    return created
