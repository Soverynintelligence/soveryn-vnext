"""House Apex + AKT catalogs as separate pickable tools."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from soveryn.platform.pondwright.catalog import search_catalog
from soveryn.platform.pondwright.tools import register_pondwright_tools
from soveryn.platform.tools.registry import ToolRegistry


@pytest.fixture
def tiny_catalogs(tmp_path: Path, monkeypatch):
    apex_items = [
        {
            "brand": "Aquascape",
            "desc": "LARGE SNORKEL VAULT AND CAP",
            "mpn": "29064",
            "msrp": 729.99,
            "map": 656.99,
            "ws": 547.49,
        },
        {
            "brand": "Aquascape",
            "desc": "SIGNATURE SERIES 2500 BIOFALLS FILTER",
            "mpn": "09020",
            "msrp": 859.99,
            "map": 773.99,
            "ws": 644.99,
        },
    ]
    akt_items = [
        {
            "source": "akt",
            "brand": "PondGard",
            "desc": "PONDGARD 10' X 20' (45 mil. EPDM)",
            "mpn": "PL1020",
            "ws": 284.0,
            "handle": "pondgard-10-x-20-45-mil-epdm",
        }
    ]
    apex = tmp_path / "apex.json"
    akt = tmp_path / "akt.json"
    apex.write_text(json.dumps(apex_items), encoding="utf-8")
    akt.write_text(json.dumps(akt_items), encoding="utf-8")
    monkeypatch.setenv("SOVERYN_PONDWRIGHT_CATALOG", str(apex))
    monkeypatch.setenv("SOVERYN_AKT_CATALOG", str(akt))
    from soveryn.platform.pondwright import catalog as cat

    cat._CACHE["apex"].update({"mtime": None, "items": None, "path": None})
    cat._CACHE["akt"].update({"mtime": None, "items": None, "path": None})
    return apex, akt


def test_apex_and_akt_stay_separate(tiny_catalogs):
    apex = search_catalog("snorkel", source="apex")
    assert apex["ok"] and apex["results"][0]["mpn"] == "29064"
    assert apex["results"][0]["retail"] == 656.99

    akt = search_catalog("pondgard", source="akt")
    assert akt["ok"] and akt["results"][0]["mpn"] == "PL1020"
    assert akt["results"][0]["source"] == "akt"

    # Apex search must not return AKT rows
    mixed = search_catalog("pondgard", source="apex")
    assert mixed["ok"] is True
    assert mixed["count"] == 0


def test_separate_tools_registered(tiny_catalogs, tmp_path, monkeypatch):
    book = tmp_path / "pricing_book.json"
    monkeypatch.setenv("SOVERYN_PONDWRIGHT_PRICING_BOOK", str(book))
    reg = ToolRegistry()
    register_pondwright_tools(reg, owner_agent="vett")
    names = sorted(n for (o, n) in reg._tools if o == "vett")
    assert "apex_catalog_search" in names
    assert "akt_catalog_search" in names
    assert "pondwright_catalog_search" not in names

    apex_hit = reg.invoke("vett", "apex_catalog_search", {"query": "biofalls"})
    assert apex_hit["results"][0]["mpn"] == "09020"

    akt_hit = reg.invoke("vett", "akt_catalog_search", {"query": "pondgard"})
    assert akt_hit["results"][0]["mpn"] == "PL1020"

    book_out = reg.invoke("vett", "pondwright_pricing_book", {})
    ids = [c["id"] for c in book_out["catalogs"]]
    assert ids == ["apex", "akt"]
    assert book_out["catalogs"][0]["tool"] == "apex_catalog_search"
    assert book_out["catalogs"][1]["tool"] == "akt_catalog_search"
