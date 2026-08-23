"""Search house dealer catalogs: Apex (MAP/MSRP/WS) + AKT Specialty (storefront WS)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

_DEFAULT_CATALOG = Path.home() / "pondpro" / "catalog.json"
_DEFAULT_AKT = Path.home() / "pondpro" / "akt_catalog.json"
_DEFAULT_XLSX = (
    Path.home() / "Pictures" / "Apex Distribution Master Price List 2026v2.xlsx"
)

# Soft cache so every tool call doesn't re-parse thousands of rows.
_CACHE: dict[str, Any] = {
    "apex": {"mtime": None, "items": None, "path": None},
    "akt": {"mtime": None, "items": None, "path": None},
}


def catalog_path() -> Path:
    override = os.environ.get("SOVERYN_PONDWRIGHT_CATALOG", "").strip()
    if override:
        return Path(override).expanduser()
    return _DEFAULT_CATALOG


def akt_catalog_path() -> Path:
    override = os.environ.get("SOVERYN_AKT_CATALOG", "").strip()
    if override:
        return Path(override).expanduser()
    return _DEFAULT_AKT


def apex_xlsx_path() -> Path:
    override = os.environ.get("SOVERYN_APEX_PRICE_LIST", "").strip()
    if override:
        return Path(override).expanduser()
    return _DEFAULT_XLSX


def _load_json_list(path: Path, *, cache_key: str, force: bool = False) -> list[dict[str, Any]]:
    slot = _CACHE[cache_key]
    if not path.is_file():
        slot.update({"mtime": None, "items": [], "path": str(path)})
        return []
    mtime = path.stat().st_mtime
    if (
        not force
        and slot["items"] is not None
        and slot["mtime"] == mtime
        and slot["path"] == str(path)
    ):
        return slot["items"]  # type: ignore[return-value]
    items = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(items, list):
        raise ValueError(f"catalog must be a JSON array: {path}")
    # Normalize source tag
    normed: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        row = dict(it)
        row.setdefault("source", "apex" if cache_key == "apex" else "akt")
        normed.append(row)
    slot["mtime"] = mtime
    slot["items"] = normed
    slot["path"] = str(path)
    return normed


def load_catalog(*, force: bool = False) -> list[dict[str, Any]]:
    return _load_json_list(catalog_path(), cache_key="apex", force=force)


def load_akt_catalog(*, force: bool = False) -> list[dict[str, Any]]:
    return _load_json_list(akt_catalog_path(), cache_key="akt", force=force)


def _tokens(q: str) -> list[str]:
    return [t for t in (q or "").lower().split() if t]


def _score_item(it: dict[str, Any], *, q: str, toks: list[str]) -> int | None:
    hay = " ".join(
        [
            str(it.get("brand") or ""),
            str(it.get("desc") or ""),
            str(it.get("mpn") or ""),
            str(it.get("sku") or ""),
        ]
    ).lower()
    if not all(t in hay for t in toks):
        return None
    score = 0
    mpn = str(it.get("mpn") or it.get("sku") or "").lower()
    desc = str(it.get("desc") or "").lower()
    if q.lower() == mpn or (len(toks) == 1 and toks[0] == mpn):
        score += 100
    if all(t in desc for t in toks):
        score += 10
    if any(t == mpn for t in toks):
        score += 40
    # Slight preference for Apex when both match (has MAP/MSRP for retail quotes)
    if (it.get("source") or "apex") == "apex":
        score += 1
    return score


def _format_hit(it: dict[str, Any]) -> dict[str, Any]:
    source = str(it.get("source") or "apex")
    msrp, map_p, ws = it.get("msrp"), it.get("map"), it.get("ws")
    if source == "akt":
        # AKT storefront (logged-in dealer) price — house cost / dealer list.
        retail = None
        retail_basis = None
        note = "AKT dealer storefront price in ws — not customer MAP/MSRP"
    else:
        retail = map_p if map_p is not None else msrp
        retail_basis = "map" if map_p is not None else ("msrp" if msrp is not None else None)
        note = None
    row = {
        "source": source,
        "brand": it.get("brand"),
        "desc": it.get("desc"),
        "mpn": it.get("mpn") or it.get("sku"),
        "msrp": msrp,
        "map": map_p,
        "ws": ws,
        "retail": retail,
        "retail_basis": retail_basis,
    }
    if note:
        row["note"] = note
    if it.get("handle"):
        row["url"] = f"https://www.aktspecialty.com/products/{it['handle']}"
    return row


def search_catalog(
    query: str,
    *,
    brand: str | None = None,
    limit: int = 15,
    source: str = "all",
) -> dict[str, Any]:
    """Token-AND search. source: all | apex | akt.

    Apex: customer retail = MAP else MSRP; ws = Apex wholesale.
    AKT: ws = logged-in dealer storefront price (no MAP sheet).
    """
    q = (query or "").strip()
    if not q:
        return {"ok": False, "error": "query required", "results": []}
    limit = max(1, min(int(limit), 50))
    src = (source or "all").strip().lower()
    if src not in ("all", "apex", "akt"):
        return {"ok": False, "error": "source must be all|apex|akt", "results": []}

    pools: list[dict[str, Any]] = []
    if src in ("all", "apex"):
        pools.extend(load_catalog())
    if src in ("all", "akt"):
        pools.extend(load_akt_catalog())

    if not pools:
        return {
            "ok": False,
            "error": "no catalogs loaded",
            "results": [],
            "hint": (
                "Apex: python pondpro/tools/import_apex_catalog.py; "
                "AKT: pondpro/tools/import_akt_catalog.py (needs login state)"
            ),
        }

    brand_f = (brand or "").strip().lower() or None
    toks = _tokens(q)
    hits: list[tuple[int, dict[str, Any]]] = []
    for it in pools:
        if brand_f and brand_f not in str(it.get("brand") or "").lower():
            continue
        score = _score_item(it, q=q, toks=toks)
        if score is None:
            continue
        hits.append((score, it))

    hits.sort(key=lambda pair: (-pair[0], str(pair[1].get("desc") or "")))
    results = [_format_hit(it) for _, it in hits[:limit]]

    return {
        "ok": True,
        "query": q,
        "brand": brand,
        "source_filter": src,
        "count": len(results),
        "total_apex": len(load_catalog()) if src in ("all", "apex") else 0,
        "total_akt": len(load_akt_catalog()) if src in ("all", "akt") else 0,
        "apex_path": str(catalog_path()),
        "akt_path": str(akt_catalog_path()),
        "note": (
            "Apex retail = MAP else MSRP; Apex/AKT ws is house dealer cost — "
            "never quote wholesale to customers."
        ),
        "results": results,
    }


def catalog_stats() -> dict[str, Any]:
    apex = load_catalog()
    akt = load_akt_catalog()
    brands: dict[str, int] = {}
    priced = 0
    for it in apex:
        b = str(it.get("brand") or "?")
        brands[b] = brands.get(b, 0) + 1
        if it.get("map") is not None or it.get("msrp") is not None:
            priced += 1
    akt_brands: dict[str, int] = {}
    for it in akt:
        b = str(it.get("brand") or "?")
        akt_brands[b] = akt_brands.get(b, 0) + 1
    return {
        "ok": True,
        "apex": {
            "path": str(catalog_path()),
            "xlsx": str(apex_xlsx_path()),
            "xlsx_present": apex_xlsx_path().is_file(),
            "skus": len(apex),
            "priced": priced,
            "brands": dict(sorted(brands.items(), key=lambda kv: (-kv[1], kv[0]))),
            "mtime": time.ctime(catalog_path().stat().st_mtime)
            if catalog_path().is_file()
            else None,
        },
        "akt": {
            "path": str(akt_catalog_path()),
            "url": "https://www.aktspecialty.com/",
            "skus": len(akt),
            "brands": dict(sorted(akt_brands.items(), key=lambda kv: (-kv[1], kv[0]))[:20]),
            "mtime": time.ctime(akt_catalog_path().stat().st_mtime)
            if akt_catalog_path().is_file()
            else None,
        },
    }
