"""CWG tax book — definition only; the ledger engine stays in core."""

from __future__ import annotations

from soveryn.plugins.api import BookDef

CWG_BOOK = BookDef(
    id="cwg",
    csv_rel="docs/ops/tax-cwg/CWG-2025-2026-expense-ledger.csv",
    evidence_rel="docs/ops/tax-cwg/evidence",
    classify_terms=(
        "aquascape",
        "hiblow",
        "dewenwils",
        "carolina water garden",
        "pond bacteria",
        "pond dosing",
        "koi pond",
        "pond liner",
        "waterfall",
        "aerator",
        "uv bulb",
        "uv light",
        "color-changing",
        "color changing",
        "pond and garden",
        "pond spotlight",
        "smart control hub",
        "carolinawatergardens",
    ),
    name_regex=r"cwg",
    domain_signals=("carolinawatergardens.com",),
    exclusive_domain=True,
    quote_needles=("pondwright", "carolina water", "pond package"),
    chat_regex=r"\bcwg\b|carolina water",
)


def books() -> list[BookDef]:
    return [CWG_BOOK]
