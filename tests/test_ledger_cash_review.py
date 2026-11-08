"""Fail-closed cash + reviewed vendor/amount_usd. Isolated temp books.

Sanitized synthetic OCR only. No real photos, no house ledgers, no Harbor Freight
parser special-case. Operator-reviewed values live only in corrections.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from soveryn.platform.intake.pdf import ExtractResult
from soveryn.platform.ledgers.books import CSV_FIELDS, changes_path, load_rows
from soveryn.platform.ledgers.ingest import (
    canonical_cents,
    ingest_path,
    normalize_corrections,
    peek_confirm_token,
)
from soveryn.platform.ledgers.parse import parse_receipt
from soveryn.platform.tools.registry import ToolArgError

# Derivative-1 shape: well-formed cents, printed total disagrees with
# subtotal+tax, card disagrees with both. Values are the reported OCR, not SKU guesses.
OCR_MISMATCH = """
STOREFRONT SALE
01-15-26
ITEM A    34.99
ITEM B    49.99
SUBTOTAL: 84.98
TAX: 5.94
TOTAL: 30.92
AMOUNT: 90.32
"""

# Derivative-2 shape: broken OCR spacing / missing decimal. Do not invent cents.
OCR_GARBLED_CENTS = """
STOREFRONT SALE
01-15-26
SUBTOTAL: $8498
TAX: $5 94
TOTAL: $30 92
"""

OCR_MATCHING_UNKNOWN_VENDOR = """
STOREFRONT SALE
01-15-26
SUBTOTAL: 84.98
TAX: 5.94
TOTAL: 90.92
AMOUNT: 90.92
"""

OCR_TOTAL_CARD_CONFLICT = """
STOREFRONT SALE
01-15-26
TOTAL: 30.92
AMOUNT: 90.32
"""

OCR_MISSING_AMOUNT = """
STOREFRONT SALE
01-15-26
THANKS FOR YOUR VISIT
"""

LOWES_MATCHING = """
LOWE'S HOME CENTERS, LLC
SALE
11-07-26
111111 15-02 PRO 2X FLOR ORANGE     14.64
222222 15-02 PRO FLRSCNT ORANGE     14.64
333333 15-02 PR WRKG CAUTION BLU    14.64
SUBTOTAL: 43.92
INVOICE 79316
TOTAL TAX: 3.07
TOTAL: 46.99
MC: XXXXXXXXXX6327 AMOUNT: 46.99
"""

REVIEW = {
    "vendor": "Acme Hardware",
    "amount_usd": "90.92",
    "review_provenance": "operator reviewed source image",
    "review_rationale": "source image shows subtotal 84.98 tax 5.94 cash 90.92",
}


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
    photo = tmp_path / "receipt.jpg"
    photo.write_bytes(b"synthetic-receipt-bytes")
    return {
        "photo": photo,
        "sov": sov,
        "cwg": cwg,
        "kw": dict(
            books={"soveryn": sov, "cwg": cwg},
            evidence_roots={"soveryn": tmp_path / "ev-s", "cwg": tmp_path / "ev-c"},
            extract=lambda _p: _extract(text, "receipt.jpg"),
            book="cwg",
        ),
    }


def test_mismatch_is_not_documented_and_does_not_present_recompute():
    row = parse_receipt(OCR_MISMATCH, source_name="receipt.jpg")
    assert row.vendor == "unknown"
    assert row.subtotal == "84.98"
    assert row.tax == "5.94"
    assert row.printed_total == "30.92"
    assert row.card_amount == "90.32"
    assert row.amount_usd == ""
    assert row.status == "NEED_REVIEW"
    assert row.status != "DOCUMENTED"
    assert "90.92" in row.notes
    assert "30.92" in row.notes
    assert "90.32" in row.notes
    assert "booking recompute" not in row.notes.lower()
    assert "ocr candidates" in row.notes


def test_garbled_cents_do_not_invent_amount():
    row = parse_receipt(OCR_GARBLED_CENTS, source_name="receipt.jpg")
    assert row.amount_usd == ""
    assert row.subtotal == ""
    assert row.tax == ""
    assert row.printed_total == ""
    assert row.status == "NEED_INVOICE"
    assert row.gap


def test_matching_cash_unknown_vendor_is_not_documented():
    row = parse_receipt(OCR_MATCHING_UNKNOWN_VENDOR, source_name="receipt.jpg")
    assert row.vendor == "unknown"
    assert row.amount_usd == "90.92"
    assert row.printed_total == "90.92"
    assert row.subtotal == "84.98"
    assert row.tax == "5.94"
    assert row.status == "NEED_REVIEW"
    assert row.status != "DOCUMENTED"


def test_filename_is_not_a_vendor_or_cash_special_case():
    row = parse_receipt(OCR_MISMATCH, source_name="harbor-freight.jpg")
    assert row.vendor == "unknown"
    assert row.amount_usd == ""
    assert row.status != "DOCUMENTED"


def test_card_vs_printed_without_breakdown_is_not_documented():
    row = parse_receipt(OCR_TOTAL_CARD_CONFLICT, source_name="receipt.jpg")
    assert row.printed_total == "30.92"
    assert row.card_amount == "90.32"
    assert row.amount_usd == ""
    assert row.status == "NEED_REVIEW"


def test_lowes_matching_46_99_stays_documented():
    row = parse_receipt(LOWES_MATCHING, source_name="receipt.jpg")
    assert row.vendor == "Lowe's"
    assert row.amount_usd == "46.99"
    assert row.subtotal == "43.92"
    assert row.tax == "3.07"
    assert row.printed_total == "46.99"
    assert row.status == "DOCUMENTED"


def test_known_vendor_listed_only_total_is_not_documented():
    """Lone TOTAL is uncorroborated even when the vendor dictionary hits."""
    row = parse_receipt(
        "LOWE'S HOME CENTERS, LLC\nSALE\n01-15-26\nTOTAL: 90.92\n",
        source_name="receipt.jpg",
    )
    assert row.vendor == "Lowe's"
    assert row.printed_total == "90.92"
    assert row.subtotal == ""
    assert row.tax == ""
    assert row.amount_usd == ""
    assert row.status == "NEED_REVIEW"
    assert row.status != "DOCUMENTED"
    assert "uncorroborated" in (row.gap or "")


def test_canonical_cents_rejects_malformed_negative_nonfinite_exponent():
    assert canonical_cents("90.92") == "90.92"
    assert canonical_cents("0.01") == "0.01"
    for bad in (
        "-1.00",
        "0.00",
        "90.920",
        "90.9",
        "1e2",
        "1E+2",
        "90.92e0",
        "NaN",
        "Infinity",
        "+90.92",
        "$90.92",
        "1,090.92",
        "010.00",
        "1000000.00",
        "90",
        "90.",
        ".92",
    ):
        with pytest.raises(ValueError):
            canonical_cents(bad)


def test_money_review_requires_image_provenance_not_filename_or_purpose():
    with pytest.raises(ValueError, match="review_provenance"):
        normalize_corrections({"amount_usd": "90.92", "purpose": "looks right"})
    with pytest.raises(ValueError, match="filename"):
        normalize_corrections(
            {
                "vendor": "Acme Hardware",
                "review_provenance": "inferred from filename",
                "review_rationale": "the file is named acme.jpg",
            }
        )
    with pytest.raises(ValueError, match="filename"):
        normalize_corrections(
            {
                **REVIEW,
                "review_rationale": "acme.jpg",
            }
        )
    with pytest.raises(ValueError, match="not supported"):
        normalize_corrections({**REVIEW, "subtotal": "84.98", "tax": "5.94"})
    out = normalize_corrections(REVIEW)
    assert out["amount_usd"] == "90.92"
    assert out["vendor"] == "Acme Hardware"
    assert out["review_provenance"] == "operator reviewed source image"


def test_mismatch_preview_is_diagnostic_not_accepted(tmp_path: Path):
    ctx = _books(tmp_path, OCR_MISMATCH)
    preview = ingest_path(ctx["photo"], confirm=False, **ctx["kw"])
    assert preview.action == "preview"
    assert preview.confirm_token
    row = preview.row
    assert row is not None
    assert row["amount_usd"] == ""
    assert row["printed_total"] == "30.92"
    assert row["subtotal"] == "84.98"
    assert row["tax"] == "5.94"
    assert row["status"] == "NEED_REVIEW"
    assert row["vendor"] == "unknown"
    assert preview.ocr is not None
    assert preview.ocr["printed_total"] == "30.92"
    assert preview.ocr["card_amount"] == "90.32"
    assert preview.ocr["amount_usd"] == ""
    assert "90.92" in (row["notes"] or "")
    assert preview.ocr_gap and "disagree" in preview.ocr_gap
    assert preview.gap and "review" in preview.gap.lower()
    assert preview.row["status"] == "NEED_REVIEW"
    assert load_rows(ctx["cwg"]) == []


def test_override_reason_does_not_book_mismatch(tmp_path: Path):
    ctx = _books(tmp_path, OCR_MISMATCH)
    blocked = ingest_path(
        ctx["photo"],
        confirm=True,
        override_reason="looks like ninety dollars",
        **ctx["kw"],
    )
    assert blocked.action == "blocked"
    assert "override_reason is not permission" in (blocked.message or "")
    assert load_rows(ctx["cwg"]) == []


def test_operator_amount_conflicting_with_breakdown_stays_blocked(tmp_path: Path):
    ctx = _books(tmp_path, OCR_MISMATCH)
    conflict = dict(REVIEW, amount_usd="30.92")
    preview = ingest_path(
        ctx["photo"], confirm=False, corrections=conflict, **ctx["kw"]
    )
    assert preview.action == "preview"
    assert preview.row is not None
    assert preview.row["printed_total"] == "30.92"
    assert preview.row["subtotal"] == "84.98"
    assert preview.row["amount_usd"] == "30.92"
    blocked = ingest_path(
        ctx["photo"],
        confirm=True,
        confirm_token=preview.confirm_token,
        corrections=conflict,
        **ctx["kw"],
    )
    assert blocked.action == "blocked"
    assert "conflicts with parsed subtotal/tax" in (blocked.message or "")
    assert "amount-only" in (blocked.message or "")
    assert load_rows(ctx["cwg"]) == []


def test_coherent_reviewed_cash_keeps_raw_printed_total(tmp_path: Path):
    ctx = _books(tmp_path, OCR_MISMATCH)
    preview = ingest_path(
        ctx["photo"], confirm=False, corrections=REVIEW, **ctx["kw"]
    )
    assert preview.action == "preview"
    row = preview.row
    assert row is not None
    assert row["amount_usd"] == "90.92"
    assert row["printed_total"] == "30.92"
    assert row["subtotal"] == "84.98"
    assert row["tax"] == "5.94"
    assert row["vendor"] == "Acme Hardware"
    assert row["status"] == "DOCUMENTED"
    assert preview.gap is None
    assert preview.ocr_gap
    assert "disagree" in preview.ocr_gap
    assert preview.ocr is not None
    assert preview.ocr["gap"] == preview.ocr_gap
    assert "ocr_gap=" in row["notes"]
    assert "disagree" in row["notes"]
    assert "vendor=unknown" in row["notes"]
    assert "amount_usd=(none)" in row["notes"]
    assert "effective amount_usd 90.92" in row["notes"]
    assert "review_provenance=operator reviewed source image" in row["notes"]
    payload = peek_confirm_token(preview.confirm_token or "")
    assert payload is not None
    assert payload["corrections"]["amount_usd"] == "90.92"
    assert payload["corrections"]["vendor"] == "Acme Hardware"
    assert payload["corrections"]["review_rationale"] == REVIEW["review_rationale"]
    assert payload["semantic"]["amount_usd"] == "90.92"
    assert payload["ocr_money"]["printed_total"] == "30.92"
    written = ingest_path(
        ctx["photo"],
        confirm=True,
        confirm_token=preview.confirm_token,
        corrections=REVIEW,
        **ctx["kw"],
    )
    assert written.action == "appended"
    rows = load_rows(ctx["cwg"])
    assert len(rows) == 1
    booked = rows[0]
    assert booked["amount_usd"] == "90.92"
    assert booked["printed_total"] == "30.92"
    assert booked["subtotal"] == "84.98"
    assert booked["tax"] == "5.94"
    assert booked["vendor"] == "Acme Hardware"
    assert booked["status"] == "DOCUMENTED"
    assert written.gap is None
    assert written.ocr_gap
    assert "disagree" in written.ocr_gap
    assert "ocr_gap=" in booked["notes"]
    log = changes_path(ctx["cwg"]).read_text(encoding="utf-8")
    assert "review_provenance=operator reviewed source image" in log
    assert "amount_usd" in log
    assert written.ocr is not None
    assert written.ocr["printed_total"] == "30.92"
    assert written.ocr["vendor"] == "unknown"


def test_missing_ocr_amount_does_not_fabricate_breakdown(tmp_path: Path):
    ctx = _books(tmp_path, OCR_MISSING_AMOUNT)
    parsed = parse_receipt(OCR_MISSING_AMOUNT, source_name="receipt.jpg")
    assert parsed.amount_usd == ""
    assert parsed.subtotal == ""
    assert parsed.tax == ""
    assert parsed.status == "NEED_INVOICE"
    preview = ingest_path(
        ctx["photo"], confirm=False, corrections=REVIEW, **ctx["kw"]
    )
    row = preview.row
    assert row is not None
    assert row["amount_usd"] == "90.92"
    assert row["subtotal"] == ""
    assert row["tax"] == ""
    assert row["printed_total"] == ""
    written = ingest_path(
        ctx["photo"],
        confirm=True,
        confirm_token=preview.confirm_token,
        corrections=REVIEW,
        **ctx["kw"],
    )
    assert written.action == "appended"
    booked = load_rows(ctx["cwg"])[0]
    assert booked["amount_usd"] == "90.92"
    assert booked["subtotal"] == ""
    assert booked["tax"] == ""
    assert booked["printed_total"] == ""


def test_unknown_vendor_matching_cash_needs_vendor_review(tmp_path: Path):
    ctx = _books(tmp_path, OCR_MATCHING_UNKNOWN_VENDOR)
    blocked = ingest_path(ctx["photo"], confirm=True, **ctx["kw"])
    assert blocked.action == "blocked"
    assert "vendor unknown" in (blocked.message or "")
    vendor_only = {
        "vendor": "Acme Hardware",
        "review_provenance": "operator reviewed source image",
        "review_rationale": "source image header is Acme Hardware",
    }
    preview = ingest_path(
        ctx["photo"], confirm=False, corrections=vendor_only, **ctx["kw"]
    )
    assert preview.row is not None
    assert preview.row["amount_usd"] == "90.92"
    assert preview.row["vendor"] == "Acme Hardware"
    assert preview.row["status"] == "DOCUMENTED"
    written = ingest_path(
        ctx["photo"],
        confirm=True,
        confirm_token=preview.confirm_token,
        corrections=vendor_only,
        **ctx["kw"],
    )
    assert written.action == "appended"
    assert load_rows(ctx["cwg"])[0]["vendor"] == "Acme Hardware"
    assert load_rows(ctx["cwg"])[0]["amount_usd"] == "90.92"


def test_changed_reason_vendor_money_file_book_and_bad_token_denied(tmp_path: Path):
    ctx = _books(tmp_path, OCR_MISMATCH)
    photo = ctx["photo"]
    kw = ctx["kw"]
    preview = ingest_path(photo, confirm=False, corrections=REVIEW, **kw)
    token = preview.confirm_token

    other = tmp_path / "other.jpg"
    other.write_bytes(b"other-synthetic-bytes")
    mismatched_file = ingest_path(
        other, confirm=True, confirm_token=token, corrections=REVIEW, **kw
    )
    assert mismatched_file.action == "blocked"
    assert load_rows(ctx["cwg"]) == []

    preview = ingest_path(photo, confirm=False, corrections=REVIEW, **kw)
    changed_reason = dict(REVIEW, review_rationale="different rationale")
    mismatched_reason = ingest_path(
        photo,
        confirm=True,
        confirm_token=preview.confirm_token,
        corrections=changed_reason,
        **kw,
    )
    assert mismatched_reason.action == "blocked"
    assert "corrections" in (mismatched_reason.message or "")
    assert load_rows(ctx["cwg"]) == []

    preview = ingest_path(photo, confirm=False, corrections=REVIEW, **kw)
    changed_vendor = dict(REVIEW, vendor="Other Hardware")
    mismatched_vendor = ingest_path(
        photo,
        confirm=True,
        confirm_token=preview.confirm_token,
        corrections=changed_vendor,
        **kw,
    )
    assert mismatched_vendor.action == "blocked"
    assert load_rows(ctx["cwg"]) == []

    preview = ingest_path(photo, confirm=False, corrections=REVIEW, **kw)
    changed_money = dict(REVIEW, amount_usd="90.91")
    mismatched_money = ingest_path(
        photo,
        confirm=True,
        confirm_token=preview.confirm_token,
        corrections=changed_money,
        **kw,
    )
    assert mismatched_money.action == "blocked"
    assert load_rows(ctx["cwg"]) == []

    preview = ingest_path(photo, confirm=False, corrections=REVIEW, **kw)
    mismatched_book = ingest_path(
        photo,
        confirm=True,
        confirm_token=preview.confirm_token,
        corrections=REVIEW,
        books=kw["books"],
        evidence_roots=kw["evidence_roots"],
        extract=kw["extract"],
        book="soveryn",
    )
    assert mismatched_book.action == "blocked"
    assert load_rows(ctx["cwg"]) == []
    assert load_rows(ctx["sov"]) == []

    missing = ingest_path(
        photo, confirm=True, confirm_token="not-a-token", corrections=REVIEW, **kw
    )
    assert missing.action == "blocked"
    assert load_rows(ctx["cwg"]) == []


def test_chat_preview_cannot_book_cash_review(tmp_path: Path):
    ctx = _books(tmp_path, OCR_MISMATCH)
    result = ingest_path(
        ctx["photo"],
        confirm=True,
        corrections=REVIEW,
        actor="chat_receipt_preview",
        **ctx["kw"],
    )
    assert result.action == "preview"
    assert load_rows(ctx["cwg"]) == []
    payload = peek_confirm_token(result.confirm_token or "")
    assert payload is not None
    assert payload["source"] == "chat_preview"
    blocked = ingest_path(
        ctx["photo"],
        confirm=True,
        confirm_token=result.confirm_token,
        corrections=REVIEW,
        **ctx["kw"],
    )
    assert blocked.action == "blocked"
    assert "chat preview token cannot book" in (blocked.message or "")
    assert load_rows(ctx["cwg"]) == []


def test_tool_rejects_raw_money_rewrite_and_bad_cents():
    from soveryn.platform.ledgers.tools import build_ledger_ingest_tool

    tool = build_ledger_ingest_tool(owner_agent="eve")
    with pytest.raises(ToolArgError, match="not supported"):
        tool.handler({"corrections": {"printed_total": "90.92"}})
    with pytest.raises(ToolArgError, match="canonical cents"):
        tool.handler(
            {
                "corrections": {
                    **REVIEW,
                    "amount_usd": "1e2",
                }
            }
        )
    with pytest.raises(ToolArgError, match="canonical cents"):
        tool.handler(
            {
                "corrections": {
                    **REVIEW,
                    "amount_usd": "-90.92",
                }
            }
        )


def test_confirm_does_not_recompute_over_operator_amount(tmp_path: Path):
    ctx = _books(tmp_path, OCR_MISMATCH)
    preview = ingest_path(
        ctx["photo"], confirm=False, corrections=REVIEW, **ctx["kw"]
    )
    payload = peek_confirm_token(preview.confirm_token or "")
    assert payload is not None
    assert payload["semantic"]["amount_usd"] == "90.92"
    assert Decimal(payload["ocr_money"]["printed_total"]) == Decimal("30.92")
    written = ingest_path(
        ctx["photo"],
        confirm=True,
        confirm_token=preview.confirm_token,
        corrections=REVIEW,
        **ctx["kw"],
    )
    assert written.row is not None
    assert written.row["amount_usd"] == "90.92"
    assert written.row["printed_total"] == "30.92"
    assert written.row["amount_usd"] != written.row["printed_total"]


LOWES_LISTED_ONLY = """
LOWE'S HOME CENTERS, LLC
SALE
01-15-26
TOTAL: 90.92
"""


def test_listed_only_known_vendor_requires_money_review(tmp_path: Path):
    ctx = _books(tmp_path, LOWES_LISTED_ONLY)
    blocked = ingest_path(ctx["photo"], confirm=True, **ctx["kw"])
    assert blocked.action == "blocked"
    assert "uncorroborated cash" in (blocked.message or "")
    assert load_rows(ctx["cwg"]) == []
    money = {
        "amount_usd": "90.92",
        "review_provenance": "operator reviewed source image",
        "review_rationale": "source image shows paid total 90.92",
    }
    preview = ingest_path(
        ctx["photo"], confirm=False, corrections=money, **ctx["kw"]
    )
    assert preview.row is not None
    assert preview.row["vendor"] == "Lowe's"
    assert preview.row["amount_usd"] == "90.92"
    assert preview.row["printed_total"] == "90.92"
    assert preview.row["subtotal"] == ""
    assert preview.row["tax"] == ""
    assert preview.row["status"] == "DOCUMENTED"
    assert preview.gap is None
    assert preview.ocr_gap and "uncorroborated" in preview.ocr_gap
    written = ingest_path(
        ctx["photo"],
        confirm=True,
        confirm_token=preview.confirm_token,
        corrections=money,
        **ctx["kw"],
    )
    assert written.action == "appended"
    assert written.gap is None
    booked = load_rows(ctx["cwg"])[0]
    assert booked["amount_usd"] == "90.92"
    assert booked["printed_total"] == "90.92"
    assert booked["status"] == "DOCUMENTED"
    assert "ocr_gap=" in booked["notes"]
