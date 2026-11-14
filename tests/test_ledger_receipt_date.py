"""Bare 'Date:' label, 'USD $X' totals, and the reviewed `date` correction.

Sanitized synthetic OCR shaped like a storefront order confirmation
(Aquascape class order 22801). No real image, no attendee contact details,
no house ledgers. Isolated temp books only.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from soveryn.platform.intake.pdf import ExtractResult
from soveryn.platform.ledgers.books import CSV_FIELDS, changes_path, load_rows
from soveryn.platform.ledgers.ingest import (
    canonical_receipt_date,
    ingest_path,
    normalize_corrections,
    peek_confirm_token,
)
from soveryn.platform.ledgers.parse import parse_receipt
from soveryn.platform.tools.registry import ToolArgError

# Layout the reader produced for the staged order screenshot: every label on
# its own line with the value on the next line.
STOREFRONT_ORDER = """Order number:

22801

Date:
November 13, 2026

Total:
USD $30.00

Payment method:
Pay with Credit Card (Mastercard
ending in 6327)

Order details

Product Total

WATER FEATURE
INSTALLATION From Basic to
Advanced

x1

Attendee Company:
Carolina Water Gardens

Attendee Type:
Contractor
"""

# Same order with no parseable date anywhere (forces the reviewed date path).
STOREFRONT_UNDATED = STOREFRONT_ORDER.replace(
    "Date:\nNovember 13, 2026\n", ""
)

DATE_REVIEW = {
    "vendor": "Aquascape",
    "amount_usd": "30.00",
    "invoice": "22801",
    "date": "2026-11-13",
    "category": "other",
    "payment": "Mercury Debit 6327",
    "review_provenance": "operator reviewed source image",
    "review_rationale": (
        "source image shows order 22801, Date November 13, 2026, "
        "Total USD $30.00"
    ),
}

MONEY_REVIEW = {k: v for k, v in DATE_REVIEW.items() if k != "date"}


def _extract(text: str, name: str) -> ExtractResult:
    return ExtractResult(
        status="ok",
        text=text,
        page_count=1,
        pages_with_text=1,
        chars=len(text),
        source_name=name,
    )


def _books(tmp_path: Path, text: str) -> dict:
    header = ",".join(CSV_FIELDS) + "\n"
    sov = tmp_path / "s.csv"
    cwg = tmp_path / "c.csv"
    sov.write_text(header, encoding="utf-8")
    cwg.write_text(header, encoding="utf-8")
    photo = tmp_path / "receipt.png"
    photo.write_bytes(b"synthetic-receipt-bytes")
    return {
        "photo": photo,
        "cwg": cwg,
        "ev": tmp_path / "ev-c",
        "kw": dict(
            books={"soveryn": sov, "cwg": cwg},
            evidence_roots={"soveryn": tmp_path / "ev-s", "cwg": tmp_path / "ev-c"},
            extract=lambda _p: _extract(text, "receipt.png"),
            book="cwg",
        ),
    }


# --- 1. bare "Date:" label -------------------------------------------------


def test_bare_date_label_value_on_next_line():
    row = parse_receipt(STOREFRONT_ORDER, source_name="receipt.png")
    assert row.date == "2026-11-13"
    assert row.tax_year == "2026"


def test_bare_date_label_value_on_same_line_and_blank_line_between():
    assert parse_receipt("Date: November 13, 2026\n").date == "2026-11-13"
    assert parse_receipt("  Date:\n\n  Nov 3, 2026\n").date == "2026-11-03"


def test_prefixed_date_labels_do_not_match_bare_rule():
    for label in ("Due Date:", "Ship Date:", "Expiration Date:"):
        row = parse_receipt(f"{label} December 1, 2026\nTotal: $5.00\n")
        assert row.date == "", label
        assert row.tax_year == "", label


def test_specific_date_labels_still_win_over_bare_date():
    text = "Order placed October 1, 2026\nDate: November 13, 2026\n"
    assert parse_receipt(text).date == "2026-10-01"


def test_bare_date_with_bad_month_stays_blank():
    assert parse_receipt("Date:\nSmarch 13, 2026\n").date == ""


# --- 2. "Total: USD $30.00" ---------------------------------------------------


def test_usd_code_before_dollar_parses_printed_total_fail_closed():
    row = parse_receipt(STOREFRONT_ORDER, source_name="receipt.png")
    assert row.printed_total == "30.00"
    # Lone listed total stays uncorroborated: no auto-booked cash.
    assert row.amount_usd == ""
    assert row.status == "NEED_REVIEW"
    assert row.gap and "uncorroborated" in row.gap


def test_bare_currency_code_requires_dollar_sign_and_known_code():
    assert parse_receipt("Total:\nUSD 30.00\n").printed_total == ""
    assert parse_receipt("Total:\nXYZ $30.00\n").printed_total == ""
    assert parse_receipt("Total: CAD $12.50\n").printed_total == "12.50"
    # Existing forms unchanged.
    assert parse_receipt("Total (USD) $10.70\n").printed_total == "10.70"
    assert parse_receipt("TOTAL: 12.34\n").printed_total == "12.34"


# --- 3. reviewed `date` correction -------------------------------------------


def test_canonical_receipt_date_accepts_iso_only():
    assert canonical_receipt_date("2026-11-13") == "2026-11-13"
    assert canonical_receipt_date(" 2026-11-13 ") == "2026-11-13"
    for bad in (
        "11/13/2026",
        "November 13, 2026",
        "2026-11-13T00:00:00",
        "20261113",
        "2026-02-30",
        "2026-13-01",
        "1999-12-31",
        "",
    ):
        with pytest.raises(ValueError):
            canonical_receipt_date(bad)
    with pytest.raises(ValueError, match="future"):
        canonical_receipt_date("2026-11-14", today=dt.date(2026, 11, 13))
    tomorrow = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    with pytest.raises(ValueError, match="future"):
        canonical_receipt_date(tomorrow)


def test_date_correction_requires_review_provenance_and_rationale():
    with pytest.raises(ValueError, match="review_provenance"):
        normalize_corrections({"date": "2026-11-13"})
    with pytest.raises(ValueError, match="review_provenance"):
        normalize_corrections(
            {"date": "2026-11-13", "review_provenance": "operator reviewed source image"}
        )
    with pytest.raises(ValueError, match="filename"):
        normalize_corrections(
            {
                "date": "2026-11-13",
                "review_provenance": "inferred from the filename",
                "review_rationale": "x",
            }
        )
    out = normalize_corrections(
        {
            "date": "2026-11-13",
            "review_provenance": "operator reviewed source image",
            "review_rationale": "source image shows Date November 13, 2026",
        }
    )
    assert out["date"] == "2026-11-13"


def test_tax_year_is_not_a_correction_and_bad_date_rejected():
    with pytest.raises(ValueError, match="derived"):
        normalize_corrections({**DATE_REVIEW, "tax_year": "2026"})
    with pytest.raises(ValueError, match="ISO date"):
        normalize_corrections({**DATE_REVIEW, "date": "11/13/2026"})


def test_tool_schema_lists_date_and_rejects_bad_date():
    from soveryn.platform.ledgers.tools import build_ledger_ingest_tool

    tool = build_ledger_ingest_tool(owner_agent="eve")
    props = tool.schema["properties"]["corrections"]["properties"]
    assert props["date"] == {"type": "string"}
    assert "tax_year" not in props
    with pytest.raises(ToolArgError, match="ISO date"):
        tool.handler({"corrections": {**DATE_REVIEW, "date": "Nov 13 2026"}})


def test_reviewed_date_sets_date_tax_year_evidence_and_audit(tmp_path: Path):
    ctx = _books(tmp_path, STOREFRONT_UNDATED)
    assert parse_receipt(STOREFRONT_UNDATED).date == ""
    # Without a date correction the planned row is undated.
    undated = ingest_path(
        ctx["photo"], confirm=False, corrections=MONEY_REVIEW, **ctx["kw"]
    )
    assert undated.row is not None
    assert undated.row["date"] == "" and undated.row["tax_year"] == ""
    assert undated.row["evidence"].startswith("evidence/undated/")

    preview = ingest_path(
        ctx["photo"], confirm=False, corrections=DATE_REVIEW, **ctx["kw"]
    )
    row = preview.row
    assert preview.action == "preview"
    assert row is not None
    assert row["date"] == "2026-11-13"
    assert row["tax_year"] == "2026"
    assert row["amount_usd"] == "30.00"
    assert row["printed_total"] == "30.00"
    assert row["status"] == "DOCUMENTED"
    assert row["evidence"].startswith("evidence/2026/2026-11-13_aquascape_")
    assert "ocr " in row["notes"] and "date=(none)" in row["notes"]
    assert "reviewed date 2026-11-13; tax_year 2026 derived" in row["notes"]
    assert "review_provenance=operator reviewed source image" in row["notes"]
    assert preview.gap is None
    payload = peek_confirm_token(preview.confirm_token or "")
    assert payload is not None
    assert payload["corrections"]["date"] == "2026-11-13"
    assert payload["semantic"]["date"] == "2026-11-13"
    assert load_rows(ctx["cwg"]) == []

    written = ingest_path(
        ctx["photo"],
        confirm=True,
        confirm_token=preview.confirm_token,
        corrections=DATE_REVIEW,
        **ctx["kw"],
    )
    assert written.action == "appended"
    booked = load_rows(ctx["cwg"])
    assert len(booked) == 1
    assert booked[0]["date"] == "2026-11-13"
    assert booked[0]["tax_year"] == "2026"
    assert booked[0]["amount_usd"] == "30.00"
    assert booked[0]["evidence"].startswith("evidence/2026/")
    assert (ctx["ev"] / booked[0]["evidence"][len("evidence/"):]).is_file()
    log = changes_path(ctx["cwg"]).read_text(encoding="utf-8")
    assert "reviewed correction" in log and "date" in log


def test_changed_date_invalidates_confirm_token(tmp_path: Path):
    ctx = _books(tmp_path, STOREFRONT_UNDATED)
    preview = ingest_path(
        ctx["photo"], confirm=False, corrections=DATE_REVIEW, **ctx["kw"]
    )
    moved = {**DATE_REVIEW, "date": "2026-11-12"}
    denied = ingest_path(
        ctx["photo"],
        confirm=True,
        confirm_token=preview.confirm_token,
        corrections=moved,
        **ctx["kw"],
    )
    assert denied.action == "blocked"
    assert "does not match these corrections" in (denied.message or "")
    assert load_rows(ctx["cwg"]) == []


def test_parsed_storefront_date_books_with_money_review_only(tmp_path: Path):
    """After the parser fix the staged shape needs no date correction."""
    ctx = _books(tmp_path, STOREFRONT_ORDER)
    preview = ingest_path(
        ctx["photo"], confirm=False, corrections=MONEY_REVIEW, **ctx["kw"]
    )
    row = preview.row
    assert row is not None
    assert row["date"] == "2026-11-13"
    assert row["tax_year"] == "2026"
    assert row["amount_usd"] == "30.00"
    assert row["status"] == "DOCUMENTED"
    assert row["evidence"].startswith("evidence/2026/")
    assert "reviewed date" not in row["notes"]
    assert preview.gap is None
    assert load_rows(ctx["cwg"]) == []
