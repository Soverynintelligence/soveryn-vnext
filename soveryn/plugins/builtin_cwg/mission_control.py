"""Mission Control CRM pipeline glance + ack (was public_agents._crm_pipeline)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from soveryn.plugins.api import MissionControlGlance

_CRM_ACK_FILE = Path.home() / ".soveryn" / "crm_ack"
_OPEN = "https://crm.pondwright.com/"
_LABEL = "PondWright CRM"


def _crm_ack_ts() -> str | None:
    try:
        raw = _CRM_ACK_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return raw if raw[:4].isdigit() else None


def crm_payload(*, ack: str | None = None) -> dict[str, Any]:
    """Live cwg-ops pipeline glance via the tower CRM client. Never raises."""
    watermark = ack if ack is not None else _crm_ack_ts()
    unavailable = {
        "ok": False,
        "error": "crm_unavailable",
        "open": _OPEN,
        "label": _LABEL,
    }
    try:
        from soveryn.platform.pondwright import crm as pw_crm

        out = pw_crm.pipeline_glance(ack=watermark)
    except Exception as exc:  # noqa: BLE001 — glance must not blank Mission Control
        unavailable["error"] = type(exc).__name__
        return unavailable
    if isinstance(out, dict):
        return out
    return unavailable


def ack_crm_new_leads() -> dict[str, Any]:
    """Owner cleared the CRM new-leads chip: watermark now, refresh counts."""
    from soveryn.app.services.public_agents import get_public_agents

    _CRM_ACK_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CRM_ACK_FILE.write_text(
        datetime.now(timezone.utc).isoformat(), encoding="utf-8"
    )
    from soveryn.app.services import public_agents as pa

    pa._cache["at"] = 0.0
    return get_public_agents(force=True)


def glance() -> MissionControlGlance:
    return MissionControlGlance(
        id="cwg-crm",
        payload=lambda ack=None: crm_payload(ack=ack),
        ack=ack_crm_new_leads,
    )
