"""In-tree CWG adapter — wraps existing modules, feeds every 2b hook.

``from soveryn.plugins.builtin_cwg import BuiltinCwgPlugin`` still works.
Step 2d will delete this package after the private ``soveryn-cwg`` soaks.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Mapping

from soveryn.citizens.connectors import ConnectorDef, signal_armed
from soveryn.plugins.api import PLUGIN_API, BookDef, MissionControlGlance, PluginBase, Worker
from soveryn.plugins.builtin_cwg.advertise import CWG_LANE
from soveryn.plugins.builtin_cwg.email import identities as cwg_email_identities
from soveryn.plugins.builtin_cwg.file_away import (
    BUCKET_HELP,
    buckets as cwg_buckets,
    photo_inbox,
)
from soveryn.plugins.builtin_cwg.ledgers import books as cwg_ledger_books
from soveryn.plugins.builtin_cwg.research import (
    accept_house_source as cwg_accept_house_source,
    research_bar as cwg_research_bar,
)
from soveryn.plugins.builtin_cwg.stale import PINS, PREFIXES

logger = logging.getLogger(__name__)

_PKG = Path(__file__).resolve().parent

# Live CWG surfaces — also listed in core CORE_ALWAYS_GATED so a future
# external plugin can never auto-approve them.
# D3 (Jon, 2026-10-02): pondwright_save_* write the live CRM and are gated.
_GATED: frozenset[str] = frozenset({
    "eve_ig_post",
    "eve_gbp_post",
    "eve_calendar_create",
    "eve_calendar_complete",
    "pondwright_save_lead",
    "pondwright_save_quote",
})

_AUTO_APPROVE: frozenset[str] = frozenset({
    "apex_catalog_search",
    "akt_catalog_search",
    "pondwright_pricing_book",
    "pondwright_catalog_refresh",
    "eve_calendar_status",
    "eve_calendar_list",
    "eve_photo_inbox",
})

_UNGATED: frozenset[str] = frozenset({
    "eve_gbp_status",
    "eve_google_desk_status",
    "pondwright_leads",
    "pondwright_jobs",
    "pondwright_customers",
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

    def prompt_fragments(self, agent: str) -> str:
        name = (agent or "").strip().lower()
        path = _PKG / "prompts" / f"{name}.md"
        if not path.is_file():
            return ""
        text = path.read_text(encoding="utf-8")
        return text

    def skills_dirs(self) -> Mapping[str, Path]:
        # Skill files stay in data/memory/skills/eve until 2c. The extra-dirs
        # hook is wired; returning the same tree would duplicate the index.
        return {}

    def routines_dirs(self) -> list[Path]:
        return [_PKG / "routines"]

    def file_away_buckets(self) -> Mapping[str, Path]:
        return cwg_buckets()

    def file_away_bucket_help(self) -> Mapping[str, str]:
        return dict(BUCKET_HELP)

    def ledger_books(self) -> list[BookDef]:
        return list(cwg_ledger_books())

    def email_identities(self) -> Mapping[str, dict[str, Any]]:
        return cwg_email_identities()

    def extra_allowed_roots(self, agent: str) -> list[Path]:
        if (agent or "").strip().lower() != "eve":
            return []
        return [photo_inbox()]

    def mission_control_glance(self) -> MissionControlGlance | None:
        from soveryn.plugins.builtin_cwg.mission_control import glance

        return glance()

    def surfaces(self) -> list[Any]:
        from soveryn.plugins.builtin_cwg.surfaces import surfaces as cwg_surfaces

        return cwg_surfaces()

    def research_bar(self, desk: str) -> str:
        return cwg_research_bar(desk)

    def accept_house_source(self, source: str, desk: str) -> bool:
        return cwg_accept_house_source(source, desk)

    def stale_prefixes(self) -> Mapping[str, int]:
        return dict(PREFIXES)

    def stale_pins(self) -> list[Any]:
        return list(PINS)

    def advertise_lane(self) -> str:
        return CWG_LANE

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
