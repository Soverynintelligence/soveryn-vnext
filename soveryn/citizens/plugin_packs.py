"""Connector packs — grant-driven tool registration (Agent Plugins Week 1).

``FOUNDING_GRANTS`` ∩ ``connector_armed`` drives which tool packs get registered
for each citizen. ``startup.py`` calls :func:`register_granted_packs` instead of
imperative per-connector loops for catalog connectors.

Non-catalog tools (lattice recall, sandbox, canva, botdirectory, dream,
intake/ledgers/QR, cron notepad, personal_files, …) stay wired in startup.

Live grant flips: citizens board is read-only today. After Week 2 install/revoke
API, restart is still required — ``ToolRegistry`` has no unregister, and packs
are registered once at boot.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from soveryn.citizens.connectors import FOUNDING_GRANTS, connector_armed

logger = logging.getLogger(__name__)

RegisterFn = Callable[["PackContext", str], None]


@dataclass
class PackContext:
    """Boot-time deps packs need. Optional fields stay None when unavailable."""

    registry: Any
    searxng_url: str = "http://127.0.0.1:8095/"
    env: Any = None
    messenger_store: Any = None
    recall_lattice: Any = None
    signal_config: Any = None
    document_store: Any = None
    delegation_store: Any = None
    active_context_service: Any = None
    embed_fn: Any = None
    # Extra opaque bag for packs that need one-off callables (X publisher, etc.)
    extras: dict[str, Any] = field(default_factory=dict)


def _ok(ctx: PackContext, owner: str, pack_id: str) -> None:
    logger.info("plugin_pack registered pack=%s owner=%s", pack_id, owner)


def _register_web(ctx: PackContext, owner: str) -> None:
    from soveryn.platform.web import register_web_tools

    register_web_tools(
        ctx.registry,
        searxng_url=ctx.searxng_url,
        owner_agent=owner,
    )
    _ok(ctx, owner, "web")


def _register_email(ctx: PackContext, owner: str) -> None:
    from soveryn.platform.email import register_email_tools

    try:
        register_email_tools(ctx.registry, owner_agent=owner)
    except Exception:
        logger.debug("email pack skip owner=%s", owner, exc_info=True)
        return
    _ok(ctx, owner, "email")


def _register_house_post(ctx: PackContext, owner: str) -> None:
    from soveryn.platform.house_post_tools import register_house_post_tools

    try:
        register_house_post_tools(ctx.registry, owner_agent=owner)
    except Exception:
        logger.debug("house_post pack skip owner=%s", owner, exc_info=True)
        return
    _ok(ctx, owner, "house_post")


def _register_pondwright(ctx: PackContext, owner: str) -> None:
    from soveryn.platform.pondwright import register_pondwright_tools

    try:
        register_pondwright_tools(ctx.registry, owner_agent=owner)
    except Exception:
        logger.exception("pondwright pack failed owner=%s", owner)
        return
    _ok(ctx, owner, "pondwright")


def _register_system(ctx: PackContext, owner: str) -> None:
    # Preserve prior startup shape: spark for aetheria/vett/scotty/eve;
    # system_probe for vett/aetheria/eve. Kernel grant is armed but had no
    # system tools registered before — keep that (no-op for kernel).
    if owner in ("aetheria", "vett", "scotty", "eve"):
        from soveryn.platform.inference.spark_status_tool import (
            register_spark_status_tool,
        )

        register_spark_status_tool(ctx.registry, owner_agent=owner)
    if owner in ("vett", "aetheria", "eve"):
        from soveryn.platform.system_probe import register_system_probe_tool

        register_system_probe_tool(ctx.registry, owner_agent=owner)
    # house_diag (2026-09-24): read-only diagnostic terminal view — see-when-
    # it's-fixed for citizens. Aetheria (verifies her watch items) + Kernel.
    # Allowlisted argv only, curl pinned to 127.0.0.1, receipts in
    # data/black_box/diag/. Edit verbs stay Kernel-only via other tools.
    if owner in ("aetheria", "kernel"):
        from soveryn.platform.diag_view_tool import build_house_diag_tool

        ctx.registry.register(build_house_diag_tool(owner_agent=owner))
    _ok(ctx, owner, "system")


def _register_delegation(ctx: PackContext, owner: str) -> None:
    if owner != "aetheria" or ctx.delegation_store is None:
        return
    from soveryn.platform.delegation.tools import register_delegation_tools

    register_delegation_tools(
        ctx.registry,
        store=ctx.delegation_store,
        owner_agent=owner,
    )
    _ok(ctx, owner, "delegation")


def _register_git(ctx: PackContext, owner: str) -> None:
    # Prior: vett (default) + eve. Kernel has git grant but did not get
    # vett_git tools — preserve (only vett/eve).
    if owner not in ("vett", "eve"):
        return
    from soveryn.agents.vett.tools import register_vett_git_tools

    if owner == "vett":
        register_vett_git_tools(ctx.registry)
    else:
        register_vett_git_tools(ctx.registry, owner_agent=owner)
    _ok(ctx, owner, "git")


def _register_patrol(ctx: PackContext, owner: str) -> None:
    if owner != "vett" or ctx.env is None:
        return
    lattice_db = getattr(ctx.env, "lattice_db", None)
    if lattice_db is None or not Path(lattice_db).is_file():
        return
    from soveryn.agents.vett.tools import register_vett_patrol_tools

    register_vett_patrol_tools(ctx.registry, lattice_db_path=lattice_db)
    _ok(ctx, owner, "patrol")


def _register_documents(ctx: PackContext, owner: str) -> None:
    # Prior: aetheria/vett/eve only (not kernel, despite kernel grant).
    if owner not in ("aetheria", "vett", "eve") or ctx.document_store is None:
        return
    from soveryn.platform.documents.tools import register_document_tools

    register_document_tools(
        ctx.registry,
        store=ctx.document_store,
        owner_agent=owner,
    )
    _ok(ctx, owner, "documents")


def _register_files(ctx: PackContext, owner: str) -> None:
    # read_file + list_directory. Scotty's files come via code pack
    # (register_scotty_tools). Preserve per-agent roots.
    if owner == "scotty":
        return
    from soveryn.agents.scotty.tools import (
        build_list_directory_tool,
        build_read_file_tool,
    )

    if owner == "aetheria":
        ctx.registry.register(build_read_file_tool(owner_agent="aetheria"))
        ctx.registry.register(build_list_directory_tool(owner_agent="aetheria"))
    elif owner == "vett":
        ctx.registry.register(build_read_file_tool(owner_agent="vett", root=Path.home()))
        ctx.registry.register(
            build_list_directory_tool(owner_agent="vett", root=Path.home())
        )
    elif owner == "eve":
        ctx.registry.register(build_read_file_tool(owner_agent="eve", root=Path.home()))
        ctx.registry.register(
            build_list_directory_tool(owner_agent="eve", root=Path.home())
        )
    elif owner == "kernel":
        ctx.registry.register(build_read_file_tool(owner_agent="kernel"))
        ctx.registry.register(build_list_directory_tool(owner_agent="kernel"))
        # 2026-09-22: the Kernel seat had read/list only — it claimed file
        # builds that never landed (demos/orrery phantom, twice). Verified
        # write hands, jailed to home, with byte + sha proof on success.
        from soveryn.agents.scotty.tools.fs import build_write_file_tool

        ctx.registry.register(
            build_write_file_tool(owner_agent="kernel", root=Path.home())
        )
    else:
        return
    _ok(ctx, owner, "files")


def _register_code(ctx: PackContext, owner: str) -> None:
    if owner == "scotty":
        from soveryn.agents.scotty.tools import register_scotty_tools

        register_scotty_tools(ctx.registry)
        _ok(ctx, owner, "code")
        return
    if owner != "kernel":
        return
    from soveryn.platform.aider_tool import build_run_aider_tool
    from soveryn.platform.opencode_tool import build_run_opencode_tool
    from soveryn.platform.kernel_child_tool import build_kernel_child_tool
    from soveryn.platform.kernel_run_tool import build_kernel_run_tool

    ctx.registry.register(build_run_aider_tool(owner_agent="kernel"))
    ctx.registry.register(build_run_opencode_tool(owner_agent="kernel"))
    ctx.registry.register(build_kernel_child_tool(owner_agent="kernel"))
    ctx.registry.register(build_kernel_run_tool(owner_agent="kernel"))
    _ok(ctx, owner, "code")


def _register_signal(ctx: PackContext, owner: str) -> None:
    # Prior: only aetheria gets signal_send (eve grant is for social delivery).
    if owner != "aetheria":
        return
    if ctx.signal_config is None or ctx.env is None:
        return
    cfg = ctx.signal_config
    if not (getattr(cfg, "bot_number", None) and getattr(cfg, "allowed_numbers", None)):
        return
    from soveryn.agents.signal_bridge.tools import register_signal_send_tool

    register_signal_send_tool(
        ctx.registry,
        config=cfg,
        lattice_db_path=ctx.env.lattice_db,
        owner_agent="aetheria",
    )
    _ok(ctx, owner, "signal")


def _register_messenger(ctx: PackContext, owner: str) -> None:
    # deliberate_share + list_my_outbound for aetheria/vett.
    # mark_share stays in startup (Aetheria-only intent grammar, not catalog).
    if owner not in ("aetheria", "vett"):
        return
    if ctx.messenger_store is None:
        return
    if ctx.recall_lattice is not None:
        from soveryn.agents.messenger_tool import build_deliberate_share_tool

        rate = None if owner == "aetheria" else 2
        ctx.registry.register(
            build_deliberate_share_tool(
                store=ctx.messenger_store,
                owner_agent=owner,
                lattice_store=ctx.recall_lattice,
                rate_limit_per_hour=rate,
            )
        )
    from soveryn.agents.messenger_introspect_tool import build_list_my_outbound_tool

    ctx.registry.register(
        build_list_my_outbound_tool(
            store=ctx.messenger_store,
            owner_agent=owner,
        )
    )
    _ok(ctx, owner, "messenger")


def _register_x(ctx: PackContext, owner: str) -> None:
    if owner != "eve":
        return
    register_x = ctx.extras.get("register_x_for_eve")
    if callable(register_x):
        register_x()
        _ok(ctx, owner, "x")


def _register_social(ctx: PackContext, owner: str) -> None:
    if owner != "eve":
        return
    env = ctx.env
    if env is not None and Path(env.lattice_db).is_file() and ctx.signal_config is not None:
        from soveryn.agents.marketing_tools import register_compose_post_tool
        from soveryn.agents.eve_ig_tools import register_eve_ig_post_tool

        register_compose_post_tool(
            ctx.registry,
            config=ctx.signal_config,
            lattice_db_path=env.lattice_db,
            owner_agent="eve",
        )
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
    _ok(ctx, owner, "social")


# connector id → register_fn
PACK_REGISTRARS: dict[str, RegisterFn] = {
    "web": _register_web,
    "email": _register_email,
    "house_post": _register_house_post,
    "pondwright": _register_pondwright,
    "system": _register_system,
    "delegation": _register_delegation,
    "git": _register_git,
    "patrol": _register_patrol,
    "documents": _register_documents,
    "files": _register_files,
    "code": _register_code,
    "signal": _register_signal,
    "messenger": _register_messenger,
    "x": _register_x,
    "social": _register_social,
}


def granted_armed_packs(owner: str) -> list[str]:
    """Return connector ids in FOUNDING_GRANTS[owner] that are currently armed."""
    grants = FOUNDING_GRANTS.get(owner, ())
    out: list[str] = []
    for pack_id in grants:
        armed, _reason = connector_armed(pack_id)
        if armed:
            out.append(pack_id)
    return out


def register_packs_for_owner(
    ctx: PackContext,
    owner: str,
    *,
    require_armed: bool = True,
) -> list[str]:
    """Register catalog packs for one owner. Returns pack ids registered."""
    grants = FOUNDING_GRANTS.get(owner, ())
    registered: list[str] = []
    for pack_id in grants:
        registrar = PACK_REGISTRARS.get(pack_id)
        if registrar is None:
            logger.warning(
                "plugin_pack: no registrar for pack=%s owner=%s", pack_id, owner
            )
            continue
        if require_armed:
            armed, reason = connector_armed(pack_id)
            if not armed:
                logger.info(
                    "plugin_pack skip unarmed pack=%s owner=%s (%s)",
                    pack_id,
                    owner,
                    reason,
                )
                continue
        try:
            registrar(ctx, owner)
            registered.append(pack_id)
        except Exception:
            logger.exception(
                "plugin_pack failed pack=%s owner=%s", pack_id, owner
            )
    return registered


def register_granted_packs(
    ctx: PackContext,
    owners: tuple[str, ...] | list[str],
    *,
    require_armed: bool = True,
) -> dict[str, list[str]]:
    """Register FOUNDING_GRANTS ∩ armed packs for each owner.

    Returns ``{owner: [pack_id, ...]}`` for what was attempted successfully.
    """
    result: dict[str, list[str]] = {}
    for owner in owners:
        result[owner] = register_packs_for_owner(
            ctx, owner, require_armed=require_armed
        )
    return result
