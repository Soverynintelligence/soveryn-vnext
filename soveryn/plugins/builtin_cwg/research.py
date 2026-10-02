"""CWG research bar + house-source acceptance."""

from __future__ import annotations

CWG_COMMISSION_BAR = (
    "\nCWG HOUSE PRICING (mandatory):\n"
    "- Pick a catalog — do not blend:\n"
    "  • `apex_catalog_search` — Aquascape/Apex MAP/MSRP/WS "
    "(customer retail = MAP else MSRP)\n"
    "  • `akt_catalog_search` — AKT Specialty dealer storefront "
    "(price in ws only; house cost)\n"
    "- Also call `pondwright_pricing_book` for labor / spring "
    "clean-out / service rates.\n"
    "- Web search is fallback only for competitor comps the house "
    "books cannot answer. Never invent prices.\n"
    "- Output a markdown table: Brand | Model/MPN | Coverage | "
    "Price | Source (Apex|AKT|rate book).\n"
)

CWG_RUNTIME_BAR = (
    "\n\nRESEARCH BAR (PondWright-grade — do not phone this in):\n"
    "- **House first:** pick a catalog — `apex_catalog_search` "
    "(Apex MAP/MSRP/WS) or `akt_catalog_search` (AKT dealer WS) — "
    "plus `pondwright_pricing_book` for labor/service rates. "
    "Catalogs are separate; do not blend them. Customer retail from "
    "Apex = MAP (else MSRP). Never quote wholesale (ws).\n"
    "- Prefer tables: Brand | Model/MPN | Coverage | Price | Source "
    "(Apex catalog / rate book).\n"
    "- Web is fallback only when the house catalog/rate book cannot "
    "answer (e.g. competitor comps). Do not dig the web for Apex/"
    "Aquascape dealer list prices that already live in the house.\n"
    "- Cite-or-stop: if you cannot verify a number, say so; never invent.\n"
)

CWG_WAVE_BAR = (
    "PondWright bar for this wave:\n"
    "- **House first:** pick `apex_catalog_search` OR `akt_catalog_search` "
    "(separate catalogs), plus `pondwright_pricing_book` for rates.\n"
    "- Extract Brand | Model/MPN | Coverage | Price | Source "
    "(Apex catalog / rate book / URL only if web fallback).\n"
    "- Customer retail = MAP else MSRP. Never publish wholesale.\n"
    "- Web only if the house book cannot answer. Cite-or-stop.\n"
    "- End with a short WAVE_SUMMARY listing new rows added or why none.\n"
)

_HOUSE_SOURCES = ("apex", "akt", "rate book", "pondwright")


def research_bar(desk: str) -> str:
    key = (desk or "").strip().lower()
    if key == "cwg":
        return CWG_COMMISSION_BAR
    if key in {"", "runtime"}:
        return CWG_RUNTIME_BAR
    if key in {"wave", "research_wave"}:
        return CWG_WAVE_BAR
    return ""


def accept_house_source(source: str, desk: str) -> bool:
    if (desk or "").strip().lower() != "cwg":
        return False
    blob = (source or "").lower()
    return any(token in blob for token in _HOUSE_SOURCES)
