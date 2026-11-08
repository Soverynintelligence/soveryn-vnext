"""Reviewed receipt field corrections before booking.

Isolated temp books. Never house ledgers. Parser is not taught this receipt.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from soveryn.platform.intake.pdf import ExtractResult
from soveryn.platform.ledgers.books import CSV_FIELDS, changes_path, load_rows
from soveryn.platform.ledgers.ingest import ingest_path, normalize_corrections, peek_confirm_token
from soveryn.platform.ledgers.parse import parse_receipt
from soveryn.platform.tools.registry import ToolArgError

# Synthetic OCR of a thermal storefront — the digits/SKU the reader produced,
# not a parser special-case. Operator-reviewed values live only in corrections.
OCR_STOREFRONT = """
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

REVIEWED = {
    "invoice": "79318",
    "description": (
        "15-OZ PRO 2X FLOR ORANGE; 15-OZ PRO FLRSCNT ORANGE; "
        "15-OZ PR WRKG CAUTION BLU"
    ),
    "category": "cogs / supplies",
    "payment": "Mercury Debit 6327",
    "purpose": "four cans marking paint for new CWG projects",
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


def _books(tmp_path: Path) -> tuple[Path, Path, dict]:
    header = ",".join(CSV_FIELDS) + "\n"
    sov = tmp_path / "s.csv"
    cwg = tmp_path / "c.csv"
    sov.write_text(header, encoding="utf-8")
    cwg.write_text(header, encoding="utf-8")
    photo = tmp_path / "receipt.jpg"
    photo.write_bytes(b"original-receipt-bytes")
    kw = dict(
        books={"soveryn": sov, "cwg": cwg},
        evidence_roots={"soveryn": tmp_path / "ev-s", "cwg": tmp_path / "ev-c"},
        extract=lambda _p: _extract(OCR_STOREFRONT, "receipt.jpg"),
        book="cwg",
    )
    return sov, cwg, {"photo": photo, "kw": kw, "sov": sov, "cwg": cwg}


def test_public_origin_main_labeled_money_required_a_dollar():
    """origin/main soveryn/platform/ledgers/parse.py _MONEY_AFTER_LABEL required `$`.

    Thermal storefront OCR for this receipt has no dollar signs. That is a
    public-parser gap, not evidence that Lowe's receipts are a new format.
    """
    origin_main = re.compile(
        r"[:\s]*-?\s*\$\s*((?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2})(?!\.?\d)"
    )
    assert origin_main.match(" 43.92") is None
    assert origin_main.match(" $43.92") is not None
    from soveryn.platform.ledgers.parse import _MONEY_AFTER_LABEL

    assert _MONEY_AFTER_LABEL.match(" 43.92") is not None


def test_ocr_limitation_is_not_parser_special_case():
    row = parse_receipt(OCR_STOREFRONT, source_name="receipt.jpg")
    assert row.amount_usd == "46.99"
    assert row.date == "2026-11-07"
    assert row.order_id == "79316"
    assert "15-02" in row.description
    assert "15-OZ" not in row.description
    assert row.schedule_c_or_form == "supplies"
    assert "6327" in row.payment_method
    assert "Mastercard" in row.payment_method
    assert "Mercury" not in row.payment_method


def test_unknown_and_malformed_corrections_rejected():
    with pytest.raises(ValueError, match="unknown correction"):
        normalize_corrections({"vendor": "Nope"})
    with pytest.raises(ValueError, match="not supported"):
        normalize_corrections({"amount_usd": "1.00"})
    with pytest.raises(ValueError, match="must be a string"):
        normalize_corrections({"invoice": 79318})
    with pytest.raises(ValueError, match="must not be empty"):
        normalize_corrections({"purpose": "   "})
    with pytest.raises(ValueError, match="conflicts"):
        normalize_corrections({"invoice": "1", "order_id": "2"})


def test_tool_rejects_bad_corrections_before_path():
    from soveryn.platform.ledgers.tools import build_ledger_ingest_tool

    tool = build_ledger_ingest_tool(owner_agent="eve")
    with pytest.raises(ToolArgError, match="unknown correction"):
        tool.handler({"corrections": {"vendor": "Nope"}})
    with pytest.raises(ToolArgError, match="not supported"):
        tool.handler({"corrections": {"total": "46.99"}})
    props = tool.schema["properties"]["corrections"]["properties"]
    assert "invoice" in props and "purpose" in props
    assert "amount_usd" not in props


def test_corrections_preview_writes_nothing_and_keeps_ocr(tmp_path: Path):
    _, cwg, ctx = _books(tmp_path)
    preview = ingest_path(
        ctx["photo"], confirm=False, corrections=REVIEWED, **ctx["kw"]
    )
    assert preview.action == "preview"
    assert preview.confirm_token
    assert "reviewed corrections" in preview.message
    assert load_rows(cwg) == []
    assert list((tmp_path / "ev-c").rglob("*")) == []
    assert preview.ocr is not None
    assert preview.ocr["order_id"] == "79316"
    assert "15-02" in preview.ocr["description"]
    assert preview.ocr["schedule_c_or_form"] == "supplies"
    assert "Mastercard" in preview.ocr["payment_method"]
    row = preview.row
    assert row is not None
    assert row["order_id"] == "79318"
    assert "15-OZ" in row["description"]
    assert "15-02" not in row["description"]
    assert row["schedule_c_or_form"] == "cogs / supplies"
    assert row["payment_method"] == "Mercury Debit 6327"
    assert row["amount_usd"] == "46.99"
    assert row["date"] == "2026-11-07"
    assert "ocr order_id=79316" in row["notes"]
    assert "operator: four cans marking paint for new CWG projects" in row["notes"]
    assert "ocr_sha256=" in row["notes"]
    payload = peek_confirm_token(preview.confirm_token)
    assert payload is not None
    assert payload["corrections"]["order_id"] == "79318"
    assert payload["semantic"]["order_id"] == "79318"
    assert payload["source"] == "ledger_ingest"
    ocr_again = parse_receipt(OCR_STOREFRONT, source_name="receipt.jpg")
    assert ocr_again.order_id == "79316"


def test_changed_corrections_book_or_file_invalidate_token(tmp_path: Path):
    _, cwg, ctx = _books(tmp_path)
    photo = ctx["photo"]
    kw = ctx["kw"]
    preview = ingest_path(photo, confirm=False, corrections=REVIEWED, **kw)
    token = preview.confirm_token
    other = tmp_path / "other.jpg"
    other.write_bytes(b"other-receipt-bytes")
    mismatched_file = ingest_path(
        other, confirm=True, confirm_token=token, corrections=REVIEWED, **kw
    )
    assert mismatched_file.action == "blocked"
    assert load_rows(cwg) == []

    preview = ingest_path(photo, confirm=False, corrections=REVIEWED, **kw)
    changed = dict(REVIEWED, invoice="00000")
    mismatched_corr = ingest_path(
        photo, confirm=True, confirm_token=preview.confirm_token, corrections=changed, **kw
    )
    assert mismatched_corr.action == "blocked"
    assert "corrections" in (mismatched_corr.message or "")
    assert load_rows(cwg) == []

    preview = ingest_path(photo, confirm=False, corrections=REVIEWED, **kw)
    mismatched_book = ingest_path(
        photo,
        confirm=True,
        confirm_token=preview.confirm_token,
        corrections=REVIEWED,
        books=kw["books"],
        evidence_roots=kw["evidence_roots"],
        extract=kw["extract"],
        book="soveryn",
    )
    assert mismatched_book.action == "blocked"
    assert load_rows(cwg) == []
    assert load_rows(ctx["sov"]) == []


def test_absent_stale_reused_token_do_not_write(tmp_path: Path):
    _, cwg, ctx = _books(tmp_path)
    photo = ctx["photo"]
    kw = ctx["kw"]
    preview = ingest_path(photo, confirm=False, corrections=REVIEWED, **kw)
    missing = ingest_path(
        photo, confirm=True, confirm_token="not-a-token", corrections=REVIEWED, **kw
    )
    assert missing.action == "blocked"
    written = ingest_path(
        photo, confirm=True, confirm_token=preview.confirm_token, **kw
    )
    assert written.action == "appended"
    reused = ingest_path(
        photo, confirm=True, confirm_token=preview.confirm_token, **kw
    )
    assert reused.action == "blocked"
    assert len(load_rows(cwg)) == 1


def test_valid_confirm_writes_corrected_row_once_with_audit(tmp_path: Path):
    _, cwg, ctx = _books(tmp_path)
    photo = ctx["photo"]
    kw = ctx["kw"]
    preview = ingest_path(photo, confirm=False, corrections=REVIEWED, **kw)
    written = ingest_path(
        photo, confirm=True, confirm_token=preview.confirm_token, corrections=REVIEWED, **kw
    )
    assert written.action == "appended"
    rows = load_rows(cwg)
    assert len(rows) == 1
    row = rows[0]
    assert row["order_id"] == "79318"
    assert "15-OZ" in row["description"]
    assert row["schedule_c_or_form"] == "cogs / supplies"
    assert row["payment_method"] == "Mercury Debit 6327"
    assert row["amount_usd"] == "46.99"
    assert "ocr order_id=79316" in row["notes"]
    assert "operator: four cans marking paint" in row["notes"]
    evidence = [p for p in (tmp_path / "ev-c").rglob("*") if p.is_file()]
    assert evidence and evidence[0].read_bytes() == b"original-receipt-bytes"
    log = changes_path(cwg).read_text(encoding="utf-8")
    assert "reviewed correction" in log
    assert "operator: four cans marking paint" in log
    assert "ocr order_id=79316" in log
    assert written.ocr is not None
    assert written.ocr["order_id"] == "79316"


def test_original_derivative_duplicate_still_detected_with_corrections(tmp_path: Path):
    _, cwg, ctx = _books(tmp_path)
    kw = ctx["kw"]
    original = tmp_path / "original.jpg"
    derivative = tmp_path / "ocr-clean.jpg"
    original.write_bytes(b"original-photo-bytes")
    derivative.write_bytes(b"ocr-derivative-bytes")
    first = ingest_path(original, confirm=False, corrections=REVIEWED, **kw)
    booked = ingest_path(
        original, confirm=True, confirm_token=first.confirm_token, corrections=REVIEWED, **kw
    )
    assert booked.action == "appended"
    second = ingest_path(derivative, confirm=False, corrections=REVIEWED, **kw)
    assert second.action == "duplicate"
    assert len(load_rows(cwg)) == 1


def test_chat_actor_preview_only_even_with_corrections(tmp_path: Path):
    _, cwg, ctx = _books(tmp_path)
    result = ingest_path(
        ctx["photo"],
        confirm=True,
        corrections=REVIEWED,
        actor="chat_receipt_preview",
        **ctx["kw"],
    )
    assert result.action == "preview"
    assert load_rows(cwg) == []
    assert list((tmp_path / "ev-c").rglob("*")) == []
    payload = peek_confirm_token(result.confirm_token or "")
    assert payload is not None
    assert payload["source"] == "chat_preview"
    blocked = ingest_path(
        ctx["photo"],
        confirm=True,
        confirm_token=result.confirm_token,
        **ctx["kw"],
    )
    assert blocked.action == "blocked"
    assert "chat preview token cannot book" in (blocked.message or "")
    assert load_rows(cwg) == []
