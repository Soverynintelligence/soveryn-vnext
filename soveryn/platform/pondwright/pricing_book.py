"""Standing PondWright service / build rates (house book).

SKU prices live in the Apex catalog. This book holds labor, liner, and the
one-time service rates Jon set in the estimator (defaults mirrored here so
citizens can quote without scraping the web).

Override path: $SOVERYN_PONDWRIGHT_PRICING_BOOK or ~/pondpro/pricing_book.json
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_DEFAULT_PATH = Path.home() / "pondpro" / "pricing_book.json"

# Seeded from pondpro/index.html defaults (Jon 2026) — edit the JSON to update.
_SEED: dict[str, Any] = {
    "version": 2,
    "source": "pondpro estimator defaults + Apex catalog + AKT Specialty",
    "apex_xlsx": str(
        Path.home() / "Pictures" / "Apex Distribution Master Price List 2026v2.xlsx"
    ),
    "catalog": str(Path.home() / "pondpro" / "catalog.json"),
    "akt_catalog": str(Path.home() / "pondpro" / "akt_catalog.json"),
    "akt_url": "https://www.aktspecialty.com/",
    "currency": "USD",

    "build": {
        "labor_cost_per_hour": 60,
        "margin_pct": 50,
        "labor_bill_per_hour_note": "cost × 1/(1-margin) → ~$120/man-hr at 50% margin",
        "liner_per_sqft": 0.98,
        "underlayment_per_sqft": 0.50,
        "rock_per_ton_hint": 245,
        "gravel_per_ton_hint": 235,
    },
    "service": {
        "service_call_per_hour": None,
        "rate_book": [
            {
                "desc": "Spring clean-out — inspect, clean pumps & filters",
                "price": 249,
            }
        ],
        "monthly_plan": {
            "includes": (
                "Auto-dosing bacteria kept filled, and a monthly inspection of "
                "pump, filter, skimmer and plumbing to confirm everything is "
                "running as designed."
            ),
            "rates_by_size": {
                "small": None,
                "medium": None,
                "large": None,
            },
            "note": (
                "Jon 2026-08-22: ~$249/mo for a typical plan including bacteria; "
                "tiers by pond size still to lock in the estimator rate book."
            ),
        },
    },
    "quote_rules": [
        "Customer-facing equipment: use MAP, else MSRP from Apex catalog.",
        "AKT Specialty prices in akt_catalog are dealer storefront (ws) — house cost, not customer MAP.",
        "Never publish wholesale (ws) to a customer quote.",
        "Service plans / clean-outs: use this rate book, not web scrapes.",
        "Full pond builds: size in the estimator; line-price equipment from catalog.",
    ],
}



def pricing_book_path() -> Path:
    override = os.environ.get("SOVERYN_PONDWRIGHT_PRICING_BOOK", "").strip()
    if override:
        return Path(override).expanduser()
    return _DEFAULT_PATH


def ensure_pricing_book() -> Path:
    path = pricing_book_path()
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_SEED, indent=2) + "\n", encoding="utf-8")
    return path


def load_pricing_book() -> dict[str, Any]:
    path = ensure_pricing_book()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = dict(_SEED)
    if not isinstance(data, dict):
        data = dict(_SEED)
    return data
