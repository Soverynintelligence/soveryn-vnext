"""Citizen tools for PondWright house pricing — separate pickable catalogs."""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from soveryn.platform.pondwright.catalog import (
    akt_catalog_path,
    catalog_path,
    catalog_stats,
    refresh_apex_catalog,
    search_catalog,
)
from soveryn.platform.pondwright import crm as pw_crm
from soveryn.platform.pondwright.pricing_book import load_pricing_book, pricing_book_path
from soveryn.platform.tools.registry import ToolArgError, ToolRegistry, ToolSpec


def _search_args(args: Mapping[str, Any]) -> tuple[str, str | None, int]:
    query = args.get("query", "")
    if not isinstance(query, str) or not query.strip():
        raise ToolArgError("query must be a non-empty string")
    brand = args.get("brand")
    if brand is not None and not isinstance(brand, str):
        raise ToolArgError("brand must be a string")
    limit = args.get("limit", 15)
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise ToolArgError("limit must be an integer")
    return query.strip(), brand, limit


_QUERY_SCHEMA_PROPS = {
    "query": {
        "type": "string",
        "description": "SKU, MPN, or words from the description.",
    },
    "brand": {
        "type": "string",
        "description": "Optional brand/vendor filter.",
    },
    "limit": {
        "type": "integer",
        "minimum": 1,
        "maximum": 50,
        "default": 15,
    },
}


def build_apex_catalog_search_tool(*, owner_agent: str) -> ToolSpec:
    def handler(args: Mapping[str, Any]) -> Any:
        query, brand, limit = _search_args(args)
        return search_catalog(query, brand=brand, limit=limit, source="apex")

    return ToolSpec(
        name="apex_catalog_search",
        owner=owner_agent,
        description=(
            "Search the **Apex Distribution** master price list only "
            f"({catalog_path()}). Aquascape, EasyPro, Oase, Blue Thumb, … "
            "Returns MAP/MSRP/wholesale. Customer retail = MAP else MSRP. "
            "Pick this catalog when quoting Apex dealer cost/list — not AKT. "
            "Never quote wholesale (ws) to customers."
        ),
        schema={
            "type": "object",
            "properties": dict(_QUERY_SCHEMA_PROPS),
            "required": ["query"],
            "additionalProperties": False,
        },
        handler=handler,
    )


def build_akt_catalog_search_tool(*, owner_agent: str) -> ToolSpec:
    def handler(args: Mapping[str, Any]) -> Any:
        query, brand, limit = _search_args(args)
        return search_catalog(query, brand=brand, limit=limit, source="akt")

    return ToolSpec(
        name="akt_catalog_search",
        owner=owner_agent,
        description=(
            "Search the **AKT Specialty** dealer catalog only "
            f"({akt_catalog_path()} — aktspecialty.com). PondGard, EasyPro, "
            "Atlantic, Aqua UV, … Dealer storefront price is in ws (no MAP). "
            "Pick this catalog when buying/pricing from AKT — not Apex. "
            "Never quote wholesale (ws) to customers."
        ),
        schema={
            "type": "object",
            "properties": dict(_QUERY_SCHEMA_PROPS),
            "required": ["query"],
            "additionalProperties": False,
        },
        handler=handler,
    )


def build_pricing_book_tool(*, owner_agent: str) -> ToolSpec:
    def handler(args: Mapping[str, Any]) -> Any:
        book = load_pricing_book()
        stats = catalog_stats()
        catalogs = [
            {
                "id": "apex",
                "label": "Apex Distribution Master Price List",
                "tool": "apex_catalog_search",
                "path": stats.get("apex", {}).get("path"),
                "skus": stats.get("apex", {}).get("skus"),
                "pick_when": "Aquascape / Apex sheet MAP-MSRP-WS quotes",
            },
            {
                "id": "akt",
                "label": "AKT Specialty (aktspecialty.com)",
                "tool": "akt_catalog_search",
                "path": stats.get("akt", {}).get("path"),
                "skus": stats.get("akt", {}).get("skus"),
                "pick_when": "AKT dealer storefront / PondGard / AKT vendors",
            },
        ]
        return {
            "ok": True,
            "pricing_book_path": str(pricing_book_path()),
            "pricing_book": book,
            "catalogs": catalogs,
            "catalog_stats": stats,
            "note": "Pick one catalog tool (apex_catalog_search or akt_catalog_search) — they are separate.",
        }

    return ToolSpec(
        name="pondwright_pricing_book",
        owner=owner_agent,
        description=(
            "Read the house PondWright rate book (labor, liner, spring clean-out) "
            "and the **list of pickable catalogs** (Apex vs AKT) with which search "
            "tool to use for each. Catalogs stay separate — pick one."
        ),
        schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        handler=handler,
    )


def build_catalog_refresh_tool(*, owner_agent: str) -> ToolSpec:
    def handler(args: Mapping[str, Any]) -> Any:
        raw = args.get("xlsx")
        xlsx = None
        if raw is not None:
            if not isinstance(raw, str) or not raw.strip():
                raise ToolArgError("xlsx must be a path string")
            xlsx = Path(raw.strip()).expanduser()
        return refresh_apex_catalog(xlsx=xlsx)

    return ToolSpec(
        name="pondwright_catalog_refresh",
        owner=owner_agent,
        description=(
            "Rebuild the Apex house catalog from the newest Master Price List "
            ".xlsx in Pictures/Downloads/Desktop (or a path you pass). "
            "Reloads SKUs so quotes use current MAP/MSRP/WS. AKT JSON is "
            "reloaded as-is (dealer scrape is a separate login). Pricing book "
            "is ~/pondpro/pricing_book.json — edit that file for labor rates."
        ),
        schema={
            "type": "object",
            "properties": {
                "xlsx": {
                    "type": "string",
                    "description": "Optional path to an Apex price-list .xlsx.",
                }
            },
            "additionalProperties": False,
        },
        handler=handler,
    )


def _opt_str(args: Mapping[str, Any], key: str) -> str | None:
    raw = args.get(key)
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str):
        raise ToolArgError(f"{key} must be a string")
    return raw.strip() or None


def build_leads_tool(*, owner_agent: str) -> ToolSpec:
    def handler(args: Mapping[str, Any]) -> Any:
        lead_id = _opt_str(args, "lead_id")
        if lead_id:
            return pw_crm.get_lead(lead_id)
        status = _opt_str(args, "status")
        query = _opt_str(args, "query")
        limit = args.get("limit", 40)
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ToolArgError("limit must be an integer")
        return pw_crm.list_leads(status=status, query=query, limit=limit)

    return ToolSpec(
        name="pondwright_leads",
        owner=owner_agent,
        description=(
            "CWG CRM: list or fetch leads (pipeline new/contacted/quoted/won/lost). "
            "Pass lead_id for one lead plus its quotes. query matches name/phone/email. "
            "This is the house lead book — not a web search."
        ),
        schema={
            "type": "object",
            "properties": {
                "lead_id": {"type": "string", "description": "Fetch one lead by id."},
                "query": {"type": "string", "description": "Name, phone, or email filter."},
                "status": {
                    "type": "string",
                    "enum": ["new", "contacted", "quoted", "won", "lost"],
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 40},
            },
            "additionalProperties": False,
        },
        handler=handler,
    )


def build_save_lead_tool(*, owner_agent: str) -> ToolSpec:
    def handler(args: Mapping[str, Any]) -> Any:
        return pw_crm.save_lead(dict(args))

    return ToolSpec(
        name="pondwright_save_lead",
        owner=owner_agent,
        description=(
            "CWG CRM: create a person, or add a note / move status on an existing "
            "lead_id. Status: new, contacted, quoted, won, lost, service. "
            "service_plan 2x/year|yearly|monthly|as-needed makes them a service "
            "customer (not a sales lead). Won opens a job. Do not leave people only in chat."
        ),
        schema={
            "type": "object",
            "properties": {
                "lead_id": {"type": "string"},
                "name": {"type": "string"},
                "phone": {"type": "string"},
                "email": {"type": "string"},
                "address": {"type": "string"},
                "interest": {"type": "string"},
                "source": {"type": "string"},
                "note": {"type": "string"},
                "service_plan": {
                    "type": "string",
                    "enum": ["2x/year", "yearly", "monthly", "as-needed"],
                    "description": "Existing service customer cadence.",
                },
                "status": {
                    "type": "string",
                    "enum": ["new", "contacted", "quoted", "won", "lost", "service"],
                },
            },
            "additionalProperties": False,
        },
        handler=handler,
    )


def build_save_quote_tool(*, owner_agent: str) -> ToolSpec:
    def handler(args: Mapping[str, Any]) -> Any:
        lines = args.get("lines")
        if lines is not None and not isinstance(lines, list):
            raise ToolArgError("lines must be an array of {desc, amount}")
        payload = dict(args)
        return pw_crm.save_quote(payload)

    return ToolSpec(
        name="pondwright_save_quote",
        owner=owner_agent,
        description=(
            "CWG CRM: attach a quote (total + line items) to a lead, or create the "
            "lead from name/phone/email if lead_id is omitted. Marks the lead quoted. "
            "Use this after Jon prices a job (pond, repair, landscape, bubbling rock)."
        ),
        schema={
            "type": "object",
            "properties": {
                "lead_id": {"type": "string"},
                "name": {"type": "string"},
                "phone": {"type": "string"},
                "email": {"type": "string"},
                "address": {"type": "string"},
                "total": {"type": "number"},
                "summary": {"type": "string"},
                "mode": {
                    "type": "string",
                    "description": "new | repair | maint",
                },
                "lines": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "desc": {"type": "string"},
                            "amount": {"type": "number"},
                            "qty": {},
                        },
                    },
                },
                "pdf_ref": {"type": "string"},
                "source": {"type": "string"},
            },
            "additionalProperties": False,
        },
        handler=handler,
    )


def build_jobs_tool(*, owner_agent: str) -> ToolSpec:
    def handler(args: Mapping[str, Any]) -> Any:
        action = args.get("action") or "list"
        if action not in ("list", "start"):
            raise ToolArgError("action must be list or start")
        if action == "start":
            lead_id = _opt_str(args, "lead_id")
            if not lead_id:
                raise ToolArgError("lead_id required to start a job")
            return pw_crm.start_job(lead_id, title=_opt_str(args, "title"))
        return pw_crm.list_jobs(
            status=_opt_str(args, "status"),
            lead_id=_opt_str(args, "lead_id"),
        )

    return ToolSpec(
        name="pondwright_jobs",
        owner=owner_agent,
        description=(
            "CWG CRM jobs: list (optional status/lead_id) or start a job on a won "
            "or open lead. Job status: scheduled, in_progress, complete."
        ),
        schema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list", "start"], "default": "list"},
                "lead_id": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["scheduled", "in_progress", "complete"],
                },
                "title": {"type": "string"},
            },
            "additionalProperties": False,
        },
        handler=handler,
    )


def build_customers_tool(*, owner_agent: str) -> ToolSpec:
    def handler(args: Mapping[str, Any]) -> Any:
        return pw_crm.list_customers(query=_opt_str(args, "query"))

    return ToolSpec(
        name="pondwright_customers",
        owner=owner_agent,
        description=(
            "CWG CRM customer history — one person over years, matched on phone/email. "
            "Optional query filters name/phone/email."
        ),
        schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
            },
            "additionalProperties": False,
        },
        handler=handler,
    )


def register_pondwright_tools(registry: ToolRegistry, *, owner_agent: str) -> None:
    registry.register(build_apex_catalog_search_tool(owner_agent=owner_agent))
    registry.register(build_akt_catalog_search_tool(owner_agent=owner_agent))
    registry.register(build_pricing_book_tool(owner_agent=owner_agent))
    registry.register(build_catalog_refresh_tool(owner_agent=owner_agent))
    registry.register(build_leads_tool(owner_agent=owner_agent))
    registry.register(build_save_lead_tool(owner_agent=owner_agent))
    registry.register(build_save_quote_tool(owner_agent=owner_agent))
    registry.register(build_jobs_tool(owner_agent=owner_agent))
    registry.register(build_customers_tool(owner_agent=owner_agent))
