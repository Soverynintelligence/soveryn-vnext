"""CWG file_away buckets — paths via SoverynPaths, never this package's __file__."""

from __future__ import annotations

import os
from pathlib import Path

from soveryn.paths import SoverynPaths


def photo_inbox() -> Path:
    raw = (os.environ.get("CWG_PHOTO_INBOX") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / "Desktop" / "CWG-Instagram"


def buckets() -> dict[str, Path]:
    root = SoverynPaths.root()
    return {
        "cwg_ig": photo_inbox(),
        "cwg_evidence": root / "docs" / "ops" / "tax-cwg" / "evidence",
        "cwg_insurance": root / "docs" / "ops" / "cwg-business" / "insurance",
        "cwg_licenses": root / "docs" / "ops" / "cwg-business" / "licenses",
        "cwg_vehicles": root / "docs" / "ops" / "cwg-business" / "vehicles",
        "cwg_contracts": root / "docs" / "ops" / "cwg-business" / "contracts",
    }


BUCKET_HELP: dict[str, str] = {
    "cwg_ig": "cwg_ig (pond photos → Desktop/CWG-Instagram)",
    "cwg_evidence": "cwg_evidence (CWG paid receipt image/PDF)",
    "cwg_insurance": "cwg_insurance (COI / insurance certificates — not bills)",
    "cwg_licenses": "cwg_licenses (licenses / EIN)",
    "cwg_vehicles": "cwg_vehicles (title / registration)",
    "cwg_contracts": "cwg_contracts (vendor contracts — not customer quotes)",
}
