"""In-tree CWG adapter — wraps existing modules, moves nothing.

This is the default ``cwg`` plugin when ``SOVERYN_PLUGINS`` is unset, or when
it is set to ``cwg`` and no external ``soveryn-cwg`` entry point imports.
Step 2d will delete this file after the private package has soaked.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from soveryn.citizens.connectors import ConnectorDef, signal_armed
from soveryn.plugins.api import PLUGIN_API, PluginBase, Worker

logger = logging.getLogger(__name__)

# Live CWG surfaces — also listed in core CORE_ALWAYS_GATED so a future
# external plugin can never auto-approve them.
_GATED: frozenset[str] = frozenset({
    "eve_ig_post",
    "eve_gbp_post",
    "eve_calendar_create",
    "eve_calendar_complete",
})

# House-local / read-only — same names core auto-approved before the split.
_AUTO_APPROVE: frozenset[str] = frozenset({
    "apex_catalog_search",
    "akt_catalog_search",
    "pondwright_pricing_book",
    "pondwright_catalog_refresh",
    "eve_calendar_status",
    "eve_calendar_list",
    "eve_photo_inbox",
})

# Explicit "no gate" (core's unknown→False). Includes the live-CRM writes
# until the D3 commit flips save_* into _GATED.
_UNGATED: frozenset[str] = frozenset({
    "eve_gbp_status",
    "eve_google_desk_status",
    "pondwright_leads",
    "pondwright_jobs",
    "pondwright_customers",
    "pondwright_save_lead",
    "pondwright_save_quote",
})


class BuiltinCwgPlugin(PluginBase):
    id = "cwg"
    api_version = PLUGIN_API
    version = "builtin"

    def connectors(self) -> tuple[ConnectorDef, ...]:
        return (
            ConnectorDef(
                id="pondwright",
                title="PondWright CRM + pricing",
                description=(
                    "CWG lead/quote/job CRM plus Apex and AKT catalogs and the estimator "
                    "rate book — not the public web."
                ),
                tools=(
                    "apex_catalog_search",
                    "akt_catalog_search",
                    "pondwright_pricing_book",
                    "pondwright_catalog_refresh",
                    "pondwright_leads",
                    "pondwright_save_lead",
                    "pondwright_save_quote",
                    "pondwright_jobs",
                    "pondwright_customers",
                ),
                class_="house",
                sovereignty_note=(
                    "CRM is pondwright-cwg-ops on the Spark (Eve ops Basic at "
                    "crm.pondwright.com / tunneled 127.0.0.1:8100). "
                    "Catalogs: Apex (xlsx) and AKT Specialty stay separate. "
                    "Wholesale stays house-only."
                ),
            ),
            ConnectorDef(
                id="cwg_social",
                title="CWG social + calendar",
                description=(
                    "CWG Instagram desk, Google Business, Google Calendar, and the "
                    "photo inbox. compose_post stays on the core social connector."
                ),
                tools=(
                    "eve_ig_post",
                    "eve_gbp_post",
                    "eve_gbp_status",
                    "eve_google_desk_status",
                    "eve_calendar_status",
                    "eve_calendar_list",
                    "eve_calendar_create",
                    "eve_calendar_complete",
                    "eve_photo_inbox",
                ),
                class_="channel",
                sovereignty_note=(
                    "eve_ig_post, eve_gbp_post, and eve_calendar_create are Gate-only "
                    "(never cadence) — CWG Instagram / Google Business / Calendar. "
                    "No password, no ads spend. Calendar list/status are read-only."
                ),
            ),
        )

    def default_grants(self) -> dict[str, tuple[str, ...]]:
        return {
            "aetheria": ("pondwright",),
            "vett": ("pondwright",),
            "eve": ("pondwright", "cwg_social"),
        }

    def armed(self, connector_id: str) -> tuple[bool, str]:
        if connector_id == "pondwright":
            return True, "house-local"
        if connector_id == "cwg_social":
            # Same gate as core `social` (compose_post delivery via Signal).
            return signal_armed()
        return False, "unknown connector"

    def register(self, ctx: Any, connector_id: str, owner: str) -> None:
        if connector_id == "pondwright":
            self._register_pondwright(ctx, owner)
            return
        if connector_id == "cwg_social":
            self._register_cwg_social(ctx, owner)
            return

    def gated_tools(self) -> frozenset[str]:
        return _GATED

    def auto_approve_tools(self) -> frozenset[str]:
        return _AUTO_APPROVE

    def automation_auto_approve_tools(self) -> frozenset[str]:
        return frozenset()

    def ungated_tools(self) -> frozenset[str]:
        return _UNGATED

    def background_workers(self, app: Any) -> list[Worker]:
        # Default ON — same as startup.py before the seam. Tests / ops disable
        # via app.config["SOVERYN_START_LEAD_WATCH"] = False.
        if app is not None and not app.config.setdefault("SOVERYN_START_LEAD_WATCH", True):
            return []
        from soveryn.platform.pondwright.lead_watch import run_forever

        return [
            Worker(
                name="pondwright-lead-watch",
                target=run_forever,
                daemon=True,
            )
        ]

    def chat_image_hooks(
        self,
    ) -> list[Callable[[str, tuple[str, ...]], str | None]]:
        def _apply(message: str, images: tuple[str, ...]) -> str | None:
            from soveryn.platform.ledgers.auto import apply_chat_receipt

            return apply_chat_receipt(message, images)

        return [_apply]

    @staticmethod
    def _register_pondwright(ctx: Any, owner: str) -> None:
        from soveryn.platform.pondwright import register_pondwright_tools

        register_pondwright_tools(ctx.registry, owner_agent=owner)
        logger.info("plugin_pack registered pack=%s owner=%s", "pondwright", owner)

    @staticmethod
    def _register_cwg_social(ctx: Any, owner: str) -> None:
        if owner != "eve":
            return
        env = ctx.env
        if (
            env is not None
            and Path(env.lattice_db).is_file()
            and ctx.signal_config is not None
        ):
            from soveryn.agents.eve_ig_tools import register_eve_ig_post_tool

            register_eve_ig_post_tool(ctx.registry, owner_agent="eve")
        try:
            from soveryn.platform.gbp import register_gbp_tools

            register_gbp_tools(ctx.registry, owner_agent="eve")
        except Exception:
            logger.exception("gbp tools not registered")
        try:
            from soveryn.platform.gcal import register_gcal_tools

            register_gcal_tools(ctx.registry, owner_agent="eve")
        except Exception:
            logger.exception("gcal tools not registered")
        try:
            from soveryn.platform.social.google_desk_tools import (
                register_google_desk_tools,
            )

            register_google_desk_tools(ctx.registry, owner_agent="eve")
        except Exception:
            logger.exception("google desk tools not registered")
        logger.info("plugin_pack registered pack=%s owner=%s", "cwg_social", owner)
