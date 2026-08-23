"""Citizen tools for PondWright house pricing — separate pickable catalogs."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from soveryn.platform.pondwright.catalog import (
    akt_catalog_path,
    catalog_path,
    catalog_stats,
    search_catalog,
)
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


def register_pondwright_tools(registry: ToolRegistry, *, owner_agent: str) -> None:
    registry.register(build_apex_catalog_search_tool(owner_agent=owner_agent))
    registry.register(build_akt_catalog_search_tool(owner_agent=owner_agent))
    registry.register(build_pricing_book_tool(owner_agent=owner_agent))
