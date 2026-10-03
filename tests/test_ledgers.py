"""Two tax books (SOVERYN vs CWG) + document-intake drop path.

Never mix the entities. Never invent a garbled total. Unsorted when unsure.
"""

from __future__ import annotations

from soveryn.paths import SoverynPaths

from pathlib import Path

from soveryn.platform.intake.pdf import ExtractResult
from soveryn.platform.kb.chunk import iter_doc_files
import json
import threading

import pytest

from soveryn.platform.ledgers.books import (
    CSV_FIELDS,
    LEGACY_FIELDS,
    append_row,
    changes_path,
    load_rows,
    write_book,
)
from soveryn.platform.ledgers.classify import classify_receipt
from soveryn.platform.ledgers.ingest import (
    FOLDER_WIDE_REFUSED,
    ingest_path,
    ingest_drop,
    split_existing_order,
)
from soveryn.platform.ledgers.parse import parse_receipt


def _extract(text: str, name: str = "receipt.pdf") -> ExtractResult:
    return ExtractResult(
        status="ok",
        text=text,
        page_count=1,
        pages_with_text=1,
        chars=len(text),
        source_name=name,
    )


AMAZON_SOVERYN = """
Order Summary
Order placed August 25, 2026  Order # 111-3866263-7187447
Prime Visa ending in 3092
Item(s) Subtotal: $3999.99Shipping & Handling: $0.00Total before tax: $3999.99Estimated tax to becollected: $280.00
Grand Total: $4279.99
ASUS Ascent GX10 DGX Spark
Sold by: Amazon.com
"""

AMAZON_CWG = """
Order Summary
Order placed April 11, 2026  Order # 111-6753422-1549820
Prime Visa ending in 3092
Item(s) Subtotal: $197.99Shipping & Handling: $0.00Total before tax: $197.99Estimated tax to becollected: $13.86
Rewards Points: -$11.21Grand Total: $200.64
Aquascape Beneficial Bacteria 1 gal contractor
Sold by: Aquascape
"""

AMAZON_GARBLED_TOTAL = """
Order Summary
Order placed April 9, 2026  Order # 111-6465328-9757805
Prime Visa ending in 3092
Item(s) Subtotal: $27.00Estimated tax to becollected: $1.90
Grand Total: $ 2.8.
be quiet! Pure Wings 3 140mm PWM
"""

DECO_MONITOR = """
DECO GEAR ORDER CONFIRMED
ORDER DG-1824708
PLACED July 16, 2026
PAYMENT Visa ending 9007
TOTAL $427.99 USD
Deco Gear 49" Curved Ultrawide White Monitor - 1-Pack
Subtotal $399.99
Shipping Free
Tax $28.00
Total $427.99 USD
"""


def test_filename_cwg_classifies_to_cwg():
    hit = classify_receipt("lightsreccwg.pdf", "Order Summary Aquascape LED")
    assert hit.book == "cwg"
    assert hit.gap is None


def test_filename_soveryn_classifies_to_soveryn():
    hit = classify_receipt("newmonitorsoveryrec.pdf", "Deco Gear ultrawide monitor")
    assert hit.book == "soveryn"
    assert hit.gap is None


def test_nvidia_text_is_soveryn_even_without_filename_hint():
    hit = classify_receipt("print.html.pdf", "NVIDIA Quadro RTX 8000 48GB")
    assert hit.book == "soveryn"


def test_aquascape_text_is_cwg_even_without_filename_hint():
    hit = classify_receipt("print.html.pdf", "Aquascape Smart Control Hub for Color-Changing Lights")
    assert hit.book == "cwg"


def test_ambiguous_or_empty_goes_unsorted_with_gap():
    hit = classify_receipt("scan.pdf", "Thanks for your order")
    assert hit.book == "unsorted"
    assert hit.gap


def test_both_entity_signals_go_unsorted():
    hit = classify_receipt(
        "mixed.pdf",
        "SOVERYN Intelligence NVIDIA Spark and Aquascape pond bacteria",
    )
    assert hit.book == "unsorted"
    assert hit.gap


def test_pondwright_quote_is_not_a_tax_receipt():
    hit = classify_receipt(
        "quote.pdf",
        "Pondwright quote for Carolina Water Gardens backyard pond package",
    )
    assert hit.book == "unsorted"
    assert "quote" in (hit.gap or "").lower() or "not a receipt" in (hit.gap or "").lower()


def test_parse_amazon_cash_is_subtotal_plus_tax_minus_rewards():
    row = parse_receipt(AMAZON_CWG, source_name="bacteria.pdf")
    assert row.order_id == "111-6753422-1549820"
    assert row.date == "2026-04-11"
    assert row.amount_usd == "200.64"
    assert row.status == "DOCUMENTED"
    assert "Amazon" in row.vendor
    assert "3092" in row.payment_method
    assert row.gap is None


def test_parse_recomputes_when_grand_total_is_garbled():
    row = parse_receipt(AMAZON_GARBLED_TOTAL, source_name="fans.pdf")
    assert row.order_id == "111-6465328-9757805"
    assert row.amount_usd == "28.90"
    assert row.status == "DOCUMENTED"
    assert row.gap is None
    assert "recompute" in row.notes.lower() or "garbled" in row.notes.lower()


def test_parse_does_not_invent_when_no_clean_money():
    row = parse_receipt(
        "Order # 111-0000000-0000000 placed January 1, 2026 Grand Total: $ .64",
        source_name="bad.pdf",
    )
    assert row.amount_usd == ""
    assert row.status != "DOCUMENTED"
    assert row.gap


OPTICS_DAC = """
OpticsWave
Confirmed Jul 11
Order #OW2026051153ON
400G QSFP112 Passive Direct Attach Copper Twinax Cable
NVIDIA / 1m / Economy 8-12days (Default)
$87.00
Subtotal $87.00
Shipping $35.00
Total USD$122.00
Ship to Jon DeOliveira
Soveryn Intelligence LLC
Return window closed on August 24, 2026.
"""


CHATGPT_PLUS = """
Receipt
Invoice number HRBTGLTD0004
Receipt number 224471062643
Date paid August 10, 2026
OpenAI OpCo, LLC
ar@openai.com
$20.00 paid on August 10, 2026
ChatGPT Plus Subscription (per seat)
Aug 10Sep 10, 2026
Subtotal $20.00
Total $20.00
Amount paid $20.00
Mastercard - 1359 August 10, 2026 $20.00
"""


def test_chatgpt_plus_classifies_soveryn_and_parses_cash():
    hit = classify_receipt("Receipt-2244-7106-2643.pdf", CHATGPT_PLUS)
    assert hit.book == "soveryn"
    row = parse_receipt(CHATGPT_PLUS, source_name="Receipt-2244-7106-2643.pdf")
    assert row.vendor == "OpenAI"
    assert row.date == "2026-08-10"
    assert row.amount_usd == "20.00"
    assert row.order_id == "HRBTGLTD0004"
    assert "1359" in row.payment_method
    assert "ChatGPT" in row.description


def test_parse_opticswave_includes_shipping_in_cash():
    row = parse_receipt(OPTICS_DAC, source_name="soveryncablesrec.pdf")
    assert row.order_id == "OW2026051153ON"
    assert row.date == "2026-07-11"
    assert row.amount_usd == "122.00"
    assert row.vendor == "OpticsWave"
    assert "QSFP" in row.description


def test_parse_deco_gear_total():
    row = parse_receipt(DECO_MONITOR, source_name="newmonitorsoveryrec.pdf")
    assert row.order_id == "DG-1824708"
    assert row.date == "2026-07-16"
    assert row.amount_usd == "427.99"
    assert "Deco" in row.vendor or "DECO" in row.vendor


MOO_CWG = """
MOO Inc.
INVOICE TO Jon DeOliveira
Carolina Water Gardens
ORDER NO #0073745198
DATE 25 Jul 2026
PAID BY Visa
**** **** **** 3092
SHIPPING COST $10.00
Standard Size Rounded Cotton Business Cards 200 $134.00
Shipping & Handling $10.00
SALES TAX (7%) $10.08
TOTAL $154.08
"""


def test_parse_moo_cwg_cards():
    row = parse_receipt(MOO_CWG, source_name="73745198-en.pdf")
    assert row.order_id == "0073745198"
    assert row.date == "2026-07-25"
    assert row.amount_usd == "154.08"
    assert "MOO" in row.vendor


def test_parse_strips_nul_bytes_from_cloudflare_invoice_number():
    row = parse_receipt(
        "Invoice number IN\x0062228858\nDate of issue April 12, 2026\n"
        "Company name Soveryn Intelligence LLC\nCloudflare, Inc.\n"
        "Registrar Registration Fee - soverynintelligence.ai\n"
        "Amount due $160.00 USD",
        source_name="cf.pdf",
    )
    assert row.order_id == "IN62228858"
    assert row.amount_usd == "160.00"
    assert "Registrar" in row.description
    assert "Townsend" not in row.description


def test_cwg_domain_on_soveryn_cloudflare_invoice_is_still_cwg():
    hit = classify_receipt(
        "invoice.pdf",
        "Company name Soveryn Intelligence LLC\n"
        "Registrar Transfer Fee - carolinawatergardens.com 1 yr)\n"
        "Amount due $10.46 USD",
    )
    assert hit.book == "cwg"


def test_ingest_soveryn_does_not_touch_cwg_book(tmp_path: Path):
    src = tmp_path / "drop" / "soveryn"
    src.mkdir(parents=True)
    pdf = src / "spark.pdf"
    pdf.write_bytes(b"%PDF-fake")
    soveryn_csv = tmp_path / "tax" / "SOVERYN-2025-2026-expense-ledger.csv"
    cwg_csv = tmp_path / "tax-cwg" / "CWG-2025-2026-expense-ledger.csv"
    soveryn_csv.parent.mkdir()
    cwg_csv.parent.mkdir()
    header = ",".join(CSV_FIELDS) + "\n"
    soveryn_csv.write_text(header, encoding="utf-8")
    cwg_csv.write_text(header, encoding="utf-8")

    result = ingest_path(
        pdf,
        books={
            "soveryn": soveryn_csv,
            "cwg": cwg_csv,
        },
        evidence_roots={
            "soveryn": tmp_path / "tax" / "evidence",
            "cwg": tmp_path / "tax-cwg" / "evidence",
        },
        extract=lambda _p: _extract(AMAZON_SOVERYN, "spark.pdf"),
    )
    assert result.book == "soveryn"
    assert result.action == "appended"
    sov = load_rows(soveryn_csv)
    cwg = load_rows(cwg_csv)
    assert len(sov) == 1
    assert sov[0]["amount_usd"] == "4279.99"
    assert "111-3866263-7187447" in sov[0]["description"]
    assert cwg == []
    evidence = list((tmp_path / "tax" / "evidence" / "2026").glob("*.pdf"))
    assert len(evidence) == 1
    assert not list((tmp_path / "tax-cwg" / "evidence").rglob("*.pdf"))


def test_ingest_cwg_does_not_touch_soveryn_book(tmp_path: Path):
    src = tmp_path / "drop" / "cwg"
    src.mkdir(parents=True)
    pdf = src / "aquascape.pdf"
    pdf.write_bytes(b"%PDF-fake")
    soveryn_csv = tmp_path / "tax" / "s.csv"
    cwg_csv = tmp_path / "tax-cwg" / "c.csv"
    soveryn_csv.parent.mkdir()
    cwg_csv.parent.mkdir()
    header = ",".join(CSV_FIELDS) + "\n"
    soveryn_csv.write_text(header, encoding="utf-8")
    cwg_csv.write_text(header, encoding="utf-8")

    result = ingest_path(
        pdf,
        books={"soveryn": soveryn_csv, "cwg": cwg_csv},
        evidence_roots={
            "soveryn": tmp_path / "tax" / "evidence",
            "cwg": tmp_path / "tax-cwg" / "evidence",
        },
        extract=lambda _p: _extract(AMAZON_CWG, "aquascape.pdf"),
    )
    assert result.book == "cwg"
    assert load_rows(soveryn_csv) == []
    rows = load_rows(cwg_csv)
    assert len(rows) == 1
    assert rows[0]["amount_usd"] == "200.64"


def test_ingest_dedupes_by_order_id(tmp_path: Path):
    csv_path = tmp_path / "s.csv"
    csv_path.write_text(",".join(CSV_FIELDS) + "\n", encoding="utf-8")
    append_row(
        csv_path,
        {
            "tax_year": "2026",
            "date": "2026-08-25",
            "vendor": "Amazon",
            "description": "Spark (order 111-3866263-7187447)",
            "schedule_c_or_form": "Form 4562 CAPEX",
            "amount_usd": "4279.99",
            "status": "DOCUMENTED",
            "payment_method": "Prime Visa 3092",
            "evidence": "already.pdf",
            "notes": "",
        },
    )
    pdf = tmp_path / "again.pdf"
    pdf.write_bytes(b"%PDF-fake")
    result = ingest_path(
        pdf,
        books={"soveryn": csv_path, "cwg": tmp_path / "c.csv"},
        evidence_roots={
            "soveryn": tmp_path / "ev-s",
            "cwg": tmp_path / "ev-c",
        },
        extract=lambda _p: _extract(AMAZON_SOVERYN, "again.pdf"),
    )
    assert result.action == "duplicate"
    assert len(load_rows(csv_path)) == 1


def test_ingest_drop_routes_each_file(tmp_path: Path):
    drop = tmp_path / "intake" / "ledgers"
    (drop / "unsorted").mkdir(parents=True)
    (drop / "soveryn").mkdir()
    (drop / "cwg").mkdir()
    (drop / "soveryn" / "spark.pdf").write_bytes(b"%PDF-s")
    (drop / "cwg" / "bacteria.pdf").write_bytes(b"%PDF-c")
    soveryn_csv = tmp_path / "s.csv"
    cwg_csv = tmp_path / "c.csv"
    header = ",".join(CSV_FIELDS) + "\n"
    soveryn_csv.write_text(header, encoding="utf-8")
    cwg_csv.write_text(header, encoding="utf-8")

    def extract(path: Path) -> ExtractResult:
        if "spark" in path.name:
            return _extract(AMAZON_SOVERYN, path.name)
        return _extract(AMAZON_CWG, path.name)

    results = ingest_drop(
        drop,
        files=[drop / "soveryn" / "spark.pdf", drop / "cwg" / "bacteria.pdf"],
        books={"soveryn": soveryn_csv, "cwg": cwg_csv},
        evidence_roots={"soveryn": tmp_path / "ev-s", "cwg": tmp_path / "ev-c"},
        extract=extract,
    )
    books = {r.source_name: r.book for r in results}
    assert books["spark.pdf"] == "soveryn"
    assert books["bacteria.pdf"] == "cwg"
    assert len(load_rows(soveryn_csv)) == 1
    assert len(load_rows(cwg_csv)) == 1


def test_kb_ingest_skips_ledger_drop_folder(tmp_path: Path):
    intake = tmp_path / "intake"
    (intake / "house").mkdir(parents=True)
    (intake / "ledgers" / "cwg").mkdir(parents=True)
    (intake / "house" / "note.md").write_text("# pond", encoding="utf-8")
    (intake / "ledgers" / "cwg" / "receipt.pdf").write_bytes(b"%PDF-1")
    files = iter_doc_files(intake)
    from soveryn.platform.ledgers.paths import is_ledger_intake

    kept = [p for p in files if not is_ledger_intake(p)]
    names = {p.name for p in kept}
    assert "note.md" in names
    assert "receipt.pdf" not in names


def test_ingest_photo_keeps_jpg_and_stays_on_hinted_book(tmp_path: Path):
    from PIL import Image

    src = tmp_path / "drop" / "cwg"
    src.mkdir(parents=True)
    jpg = src / "lowes.jpg"
    Image.new("RGB", (16, 16), (255, 255, 255)).save(jpg)
    soveryn_csv = tmp_path / "s.csv"
    cwg_csv = tmp_path / "c.csv"
    header = ",".join(CSV_FIELDS) + "\n"
    soveryn_csv.write_text(header, encoding="utf-8")
    cwg_csv.write_text(header, encoding="utf-8")

    result = ingest_path(
        jpg,
        books={"soveryn": soveryn_csv, "cwg": cwg_csv},
        evidence_roots={
            "soveryn": tmp_path / "ev-s",
            "cwg": tmp_path / "ev-c",
        },
        extract=lambda _p: ExtractResult(
            status="failed",
            text="",
            page_count=1,
            pages_with_text=0,
            chars=0,
            gap="OCR found no text on this photo — do not invent totals",
            source_name="lowes.jpg",
        ),
        folder_hint="cwg",
        book="cwg",
    )
    assert result.book == "cwg"
    assert result.action == "appended"
    assert load_rows(soveryn_csv) == []
    rows = load_rows(cwg_csv)
    assert len(rows) == 1
    assert rows[0]["status"] == "NEED_INVOICE"
    assert rows[0]["amount_usd"] == ""
    evidence = list((tmp_path / "ev-c").rglob("*.jpg"))
    assert len(evidence) == 1
    assert "photo receipt" in rows[0]["notes"]


THERMAL_POS = """
STAR RIDGE AQUATICS LLC
180 STAR RIDGE RD
CARTHAGE, NC 28327
SALE
08/29/26
Trans ID 466241492734687
VISA 5010
Contactless
AMOUNT $90.91
APPROVED
"""


def test_parse_thermal_pos_amount_and_slash_date():
    row = parse_receipt(THERMAL_POS, source_name="chat.jpg")
    assert row.vendor == "Star Ridge Aquatics"
    assert row.date == "2026-08-29"
    assert row.amount_usd == "90.91"
    assert row.order_id == "466241492734687"
    assert "5010" in row.payment_method


GMAIL_NEXT_INSURANCE = """
Gmail - Your business insurance is active
Jon DeOliveira <owner@example.test>
Your business insurance is active
Next Insurance <hello@nextinsurance.com> Sat, Sep 12, 2026 at 3:41 PM
Hi Jon,
Congratulations! Your business insurance is now active.
Policy Details
General Liability: 09/12/26 - 09/12/27
General Liability: $86.66 /mo
Payment Summary
You have agreed to pay for your policy via ACH, including
authorizing NEXT to debit the below bank account for any
amount owed, based on NEXT's terms of service.
Financial institution: Column Na Mercury
Account ending in: 2648
Your first payment has been initiated but may take a few days to
hit your bank account.
Payment date: 09/12/26
Payment amount: $163.33
Your next automatic payment will be on 10/12/2026
"""


def test_parse_gmail_next_insurance_uses_payment_amount_not_monthly():
    """Gmail printouts are not invoices. Do not book $86.66/mo or skip the total."""
    row = parse_receipt(GMAIL_NEXT_INSURANCE, source_name="cwginsurancebill.pdf")
    assert row.amount_usd == "163.33"
    assert row.status == "DOCUMENTED"
    assert row.date == "2026-09-12"
    assert "Next Insurance" in row.vendor
    assert "ACH" in row.payment_method
    assert "insurance" in row.schedule_c_or_form.lower()
    assert row.gap is None


def test_extract_real_gmail_insurance_pdf_if_present():
    import pytest
    from soveryn.platform.ledgers.extract import extract_receipt_path

    path = (
        SoverynPaths.root()
        / "docs"
        / "ops"
        / "tax-cwg"
        / "evidence"
        / "2026"
        / "2026-09-12_unknown_your-business-insurance-is-active_na-2.pdf"
    )
    if not path.is_file():
        pytest.skip("insurance Gmail PDF not on disk")
    extracted = extract_receipt_path(path)
    assert extracted.status in ("ok", "partial")
    assert "163.33" in (extracted.text or "")
    row = parse_receipt(extracted.text or "", source_name=path.name)
    assert row.amount_usd == "163.33"
    assert row.vendor == "Next Insurance"


def test_receipt_file_intent_cwg_not_instagram():
    from soveryn.platform.ledgers.auto import receipt_file_book

    assert receipt_file_book("file this on cwg") == "cwg"
    assert receipt_file_book("Log this in cwg docs /receipts") == "cwg"
    assert receipt_file_book("file this on soveryn") == "soveryn"
    assert receipt_file_book("draft an IG post for CWG") is None


def test_ingest_drop_picks_up_jpg(tmp_path: Path):
    from PIL import Image

    drop = tmp_path / "ledgers"
    (drop / "cwg").mkdir(parents=True)
    (drop / "soveryn").mkdir()
    (drop / "unsorted").mkdir()
    Image.new("RGB", (8, 8), (240, 240, 240)).save(drop / "cwg" / "pond.jpg")
    soveryn_csv = tmp_path / "s.csv"
    cwg_csv = tmp_path / "c.csv"
    header = ",".join(CSV_FIELDS) + "\n"
    soveryn_csv.write_text(header, encoding="utf-8")
    cwg_csv.write_text(header, encoding="utf-8")

    results = ingest_drop(
        drop,
        files=[drop / "cwg" / "pond.jpg"],
        books={"soveryn": soveryn_csv, "cwg": cwg_csv},
        evidence_roots={"soveryn": tmp_path / "ev-s", "cwg": tmp_path / "ev-c"},
        extract=lambda p: _extract(AMAZON_CWG, p.name),
    )
    assert results[0].book == "cwg"
    assert results[0].source_name == "pond.jpg"
    assert len(load_rows(cwg_csv)) == 1
    assert load_rows(soveryn_csv) == []


MIXED_AMAZON = """
Order Summary
Order placed September 6, 2026  Order # 111-2306725-3147467
Prime Visa ending in 3092
Item(s) Subtotal: $92.20Estimated tax to becollected: $6.45
Rewards Points: -$26.79Grand Total: $71.86
Aquascape Pond Plant Potting Media, Nutrient-Rich Aquatic Soil
Tecmojo 6U Network Rack
Sold by: Amazon.com
"""


def _two_books(tmp_path: Path):
    soveryn_csv = tmp_path / "s.csv"
    cwg_csv = tmp_path / "c.csv"
    header = ",".join(CSV_FIELDS) + "\n"
    soveryn_csv.write_text(header, encoding="utf-8")
    cwg_csv.write_text(header, encoding="utf-8")
    return soveryn_csv, cwg_csv


def test_mixed_aquascape_and_rack_is_unsorted():
    hit = classify_receipt("print.html.pdf", MIXED_AMAZON)
    assert hit.book == "unsorted"
    assert "split" in (hit.gap or "").lower()


def test_ingest_split_puts_line_amounts_on_each_book(tmp_path: Path):
    pdf = tmp_path / "mixed.pdf"
    pdf.write_bytes(b"%PDF-fake")
    soveryn_csv, cwg_csv = _two_books(tmp_path)
    result = ingest_path(
        pdf,
        books={"soveryn": soveryn_csv, "cwg": cwg_csv},
        evidence_roots={"soveryn": tmp_path / "ev-s", "cwg": tmp_path / "ev-c"},
        extract=lambda _p: _extract(MIXED_AMAZON, "mixed.pdf"),
        splits=[
            {
                "book": "cwg",
                "amount": "22.30",
                "description": "Aquascape Pond Plant Potting Media (Lilly's soil)",
            },
            {
                "book": "soveryn",
                "amount": "69.90",
                "description": "Tecmojo 6U Network Rack (for the Sparks)",
            },
        ],
    )
    assert result.action == "split"
    assert result.book == "split"
    sov = load_rows(soveryn_csv)
    cwg = load_rows(cwg_csv)
    assert len(sov) == 1
    assert len(cwg) == 1
    assert sov[0]["amount_usd"] == "69.90"
    assert cwg[0]["amount_usd"] == "22.30"
    assert "71.86" not in {sov[0]["amount_usd"], cwg[0]["amount_usd"]}
    assert "Tecmojo" in sov[0]["description"]
    assert "Aquascape" in cwg[0]["description"]
    assert "111-2306725-3147467" in sov[0]["description"]
    assert "111-2306725-3147467" in cwg[0]["description"]
    assert "Form 4562" in sov[0]["schedule_c_or_form"]
    assert "cogs" in cwg[0]["schedule_c_or_form"]


def test_full_amount_on_second_book_needs_split(tmp_path: Path):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-fake")
    soveryn_csv, cwg_csv = _two_books(tmp_path)
    first = ingest_path(
        pdf,
        books={"soveryn": soveryn_csv, "cwg": cwg_csv},
        evidence_roots={"soveryn": tmp_path / "ev-s", "cwg": tmp_path / "ev-c"},
        extract=lambda _p: _extract(MIXED_AMAZON, "a.pdf"),
        book="cwg",
    )
    assert first.action == "appended"
    assert first.amount_usd == "71.86"
    second = ingest_path(
        pdf,
        books={"soveryn": soveryn_csv, "cwg": cwg_csv},
        evidence_roots={"soveryn": tmp_path / "ev-s", "cwg": tmp_path / "ev-c"},
        extract=lambda _p: _extract(MIXED_AMAZON, "a.pdf"),
        book="soveryn",
    )
    assert second.action == "needs_split"
    assert load_rows(soveryn_csv) == []
    assert load_rows(cwg_csv)[0]["amount_usd"] == "71.86"


def test_split_existing_replaces_full_amount_on_both_books(tmp_path: Path):
    soveryn_csv, cwg_csv = _two_books(tmp_path)
    oid = "111-2306725-3147467"
    for path in (soveryn_csv, cwg_csv):
        append_row(
            path,
            {
                "tax_year": "2026",
                "date": "2026-09-06",
                "vendor": "Amazon Prime Visa 3092",
                "description": f"mixed (order {oid})",
                "schedule_c_or_form": "cogs / supplies",
                "amount_usd": "71.86",
                "status": "DOCUMENTED",
                "payment_method": "Prime Visa 3092",
                "evidence": "evidence/2026/mixed_71.86.pdf",
                "notes": "92.20 + tax 6.45 + rewards 26.79 = cash 71.86",
            },
        )
        append_row(
            path,
            {
                "tax_year": "2026",
                "date": "",
                "vendor": "Mercury",
                "description": "keep me",
                "schedule_c_or_form": "bank_charges",
                "amount_usd": "",
                "status": "NEED_EXPORT",
                "payment_method": "",
                "evidence": "",
                "notes": "",
            },
        )
    result = split_existing_order(
        oid,
        [
            {"book": "cwg", "amount": "22.30", "description": "Lilly's soil"},
            {"book": "soveryn", "amount": "69.90", "description": "Tecmojo 6U rack"},
        ],
        books={"soveryn": soveryn_csv, "cwg": cwg_csv},
        evidence_roots={"soveryn": tmp_path / "ev-s", "cwg": tmp_path / "ev-c"},
    )
    assert result.action == "split"
    sov = load_rows(soveryn_csv)
    cwg = load_rows(cwg_csv)
    assert [r["description"] for r in sov if r["description"] == "keep me"]
    assert [r["description"] for r in cwg if r["description"] == "keep me"]
    sov_amt = [r for r in sov if oid in r["description"]]
    cwg_amt = [r for r in cwg if oid in r["description"]]
    assert len(sov_amt) == 1 and sov_amt[0]["amount_usd"] == "69.90"
    assert len(cwg_amt) == 1 and cwg_amt[0]["amount_usd"] == "22.30"
    assert not any(r["amount_usd"] == "71.86" for r in sov + cwg)


APEX_ORDER_PAGE = """
Apex Distribution
My orders
My addresses
Logout
My orders
Product Quantity Total
4 oz. 15' wide Geotextile Underlayment - 15'x10'
$27.00 1 $27.00
10' Wide PondGard 45 mil EPDM Pond Liners -
8'x10'
$80.00
1 $80.00
Subtotal $107.00
Shipping (FedEx Ground\u00ae) $20.16
 Back to orders October 02, 2026 at 19:09pm
ORDER #1216
October 02, 2026 at 19:09pm
10/2/26, 7:10 PM Order #1216
https://www.apexdistribution.net/account/orders/1216
Order #1216
Total $127.16
BILLING ADDRESS
"""


def test_parse_apex_books_total_including_carrier_shipping():
    row = parse_receipt(APEX_ORDER_PAGE, source_name="chat-apex.pdf")
    assert row.vendor == "Apex Distribution"
    assert row.order_id == "1216"
    assert row.amount_usd == "127.16"
    assert "shipping 20.16" in row.notes


def test_parse_prefers_printed_total_when_shipping_line_unparsed():
    text = "Order placed May 1, 2026\nSubtotal $107.00\nFreight via LTL carrier $20.16\nTotal $127.16\n"
    row = parse_receipt(text, source_name="x.pdf")
    assert row.amount_usd == "127.16"
    assert "unitemized 20.16" in row.notes


def test_short_order_id_does_not_match_substrings():
    from soveryn.platform.ledgers.books import has_order_id

    rows = [{"description": "x (order 111-1216000-0000000)", "notes": "paid $1216.00", "evidence": "", "vendor": ""}]
    assert not has_order_id(rows, "1216")
    rows.append({"description": "Liner (order 1216)", "notes": "", "evidence": "", "vendor": ""})
    assert has_order_id(rows, "1216")


def test_reingesting_same_file_without_order_id_is_duplicate(tmp_path: Path):
    cwg = tmp_path / "c.csv"
    cwg.write_text(",".join(CSV_FIELDS) + "\n", encoding="utf-8")
    pdf = tmp_path / "chat-1.pdf"
    pdf.write_bytes(b"%PDF-receipt-no-order-id")
    text = "Aquascape pond bacteria\nOrder placed May 1, 2026\nSubtotal $10.00\nTax $0.70\nTotal $10.70\n"
    kw = dict(
        books={"soveryn": tmp_path / "s.csv", "cwg": cwg},
        evidence_roots={"soveryn": tmp_path / "ev-s", "cwg": tmp_path / "ev-c"},
        extract=lambda _p: _extract(text, "chat-1.pdf"),
        book="cwg",
    )
    first = ingest_path(pdf, **kw)
    second = ingest_path(pdf, **kw)
    assert first.action == "appended"
    assert second.action == "duplicate"
    assert second.row is not None
    assert len(load_rows(cwg)) == 1


def _ingest_kw(tmp_path: Path, csv_path: Path, text: str, name: str, book: str = "cwg"):
    return dict(
        books={"soveryn": tmp_path / "s.csv", "cwg": csv_path if book == "cwg" else tmp_path / "c.csv"},
        evidence_roots={"soveryn": tmp_path / "ev-s", "cwg": tmp_path / "ev-c"},
        extract=lambda _p: _extract(text, name),
        book=book,
    )


def test_order_1216_reingest_is_noop(tmp_path: Path):
    cwg = tmp_path / "c.csv"
    cwg.write_text(",".join(CSV_FIELDS) + "\n", encoding="utf-8")
    pdf = tmp_path / "apex-1216.pdf"
    pdf.write_bytes(b"%PDF-apex-1216")
    kw = _ingest_kw(tmp_path, cwg, APEX_ORDER_PAGE, "apex-1216.pdf")
    first = ingest_path(pdf, **kw)
    second = ingest_path(pdf, **kw)
    assert first.action == "appended"
    assert first.amount_usd == "127.16"
    assert first.row and first.row["order_id"] == "1216"
    assert second.action == "duplicate"
    assert second.row is not None
    assert second.row["row_id"] == first.row["row_id"]
    assert len(load_rows(cwg)) == 1


def test_order_id_without_splits_is_error():
    from soveryn.platform.ledgers.tools import build_ledger_ingest_tool
    from soveryn.platform.tools.registry import ToolArgError

    tool = build_ledger_ingest_tool(owner_agent="eve")
    with pytest.raises(ToolArgError, match="order_id alone"):
        tool.handler({"order_id": "1216"})


def test_folder_wide_ingest_refused_by_tool_and_library():
    from soveryn.platform.ledgers.tools import build_ledger_ingest_tool
    from soveryn.platform.tools.registry import ToolArgError

    tool = build_ledger_ingest_tool(owner_agent="eve")
    with pytest.raises(ToolArgError, match="folder-wide"):
        tool.handler({})
    with pytest.raises(ValueError, match="folder-wide"):
        ingest_drop()
    assert "specific files" in FOLDER_WIDE_REFUSED


def test_retry_storm_same_receipt_one_row(tmp_path: Path):
    cwg = tmp_path / "c.csv"
    cwg.write_text(",".join(CSV_FIELDS) + "\n", encoding="utf-8")
    pdf = tmp_path / "storm.pdf"
    pdf.write_bytes(b"%PDF-storm-same-bytes")
    kw = _ingest_kw(tmp_path, cwg, APEX_ORDER_PAGE, "storm.pdf")
    for _ in range(20):
        ingest_path(pdf, **kw)
    assert len(load_rows(cwg)) == 1

    errors: list[BaseException] = []

    def _once() -> None:
        try:
            ingest_path(pdf, **kw)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=_once) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert len(load_rows(cwg)) == 1


def test_lock_contention_two_writers(tmp_path: Path):
    book = tmp_path / "book.csv"
    book.write_text(",".join(CSV_FIELDS) + "\n", encoding="utf-8")
    errors: list[BaseException] = []

    def _append(vendor: str) -> None:
        try:
            append_row(
                book,
                {
                    "tax_year": "2026",
                    "date": "2026-10-03",
                    "vendor": vendor,
                    "description": vendor,
                    "schedule_c_or_form": "supplies",
                    "amount_usd": "1.00",
                    "status": "DOCUMENTED",
                    "payment_method": "",
                    "evidence": "",
                    "notes": "",
                },
                actor="test",
                reason="lock contention",
            )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [
        threading.Thread(target=_append, args=("Alpha",)),
        threading.Thread(target=_append, args=("Beta",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    vendors = {row["vendor"] for row in load_rows(book)}
    assert vendors == {"Alpha", "Beta"}


def test_atomic_write_survives_exception_mid_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    book = tmp_path / "book.csv"
    first = append_row(
        book,
        {
            "tax_year": "2026",
            "date": "2026-10-03",
            "vendor": "Keep",
            "description": "original",
            "schedule_c_or_form": "supplies",
            "amount_usd": "5.00",
            "status": "DOCUMENTED",
            "payment_method": "",
            "evidence": "",
            "notes": "",
        },
        actor="test",
        reason="seed",
    )
    original = book.read_bytes()

    def _boom(*_a, **_k):
        raise RuntimeError("disk full mid-write")

    monkeypatch.setattr("soveryn.platform.ledgers.books.os.replace", _boom)
    with pytest.raises(RuntimeError, match="disk full"):
        append_row(
            book,
            {
                "tax_year": "2026",
                "date": "2026-10-03",
                "vendor": "Nope",
                "description": "should not land",
                "schedule_c_or_form": "supplies",
                "amount_usd": "9.00",
                "status": "DOCUMENTED",
                "payment_method": "",
                "evidence": "",
                "notes": "",
            },
            actor="test",
            reason="fail",
        )
    assert book.read_bytes() == original
    rows = load_rows(book)
    assert len(rows) == 1
    assert rows[0]["vendor"] == "Keep"
    assert rows[0]["row_id"] == first["row_id"]


def test_preview_without_confirm_writes_nothing(tmp_path: Path):
    cwg = tmp_path / "c.csv"
    cwg.write_text(",".join(CSV_FIELDS) + "\n", encoding="utf-8")
    pdf = tmp_path / "preview.pdf"
    pdf.write_bytes(b"%PDF-preview")
    kw = _ingest_kw(tmp_path, cwg, APEX_ORDER_PAGE, "preview.pdf")
    preview = ingest_path(pdf, confirm=False, **kw)
    assert preview.action == "preview"
    assert preview.confirm_token
    assert preview.rows and preview.rows[0]["amount_usd"] == "127.16"
    assert load_rows(cwg) == []
    assert not list((tmp_path / "ev-c").rglob("*.pdf"))

    from soveryn.platform.ledgers.tools import build_ledger_ingest_tool
    from soveryn.platform.tools.registry import ToolArgError

    tool = build_ledger_ingest_tool(owner_agent="eve")
    with pytest.raises(ToolArgError, match="confirm_token"):
        tool.handler({"confirm": True})


def test_mismatch_block_and_override(tmp_path: Path):
    cwg = tmp_path / "c.csv"
    cwg.write_text(",".join(CSV_FIELDS) + "\n", encoding="utf-8")
    pdf = tmp_path / "freight.pdf"
    pdf.write_bytes(b"%PDF-freight")
    text = (
        "Aquascape pond liner\nOrder placed May 1, 2026\n"
        "Subtotal $107.00\nFreight via LTL carrier $20.16\nTotal $127.16\n"
    )
    kw = _ingest_kw(tmp_path, cwg, text, "freight.pdf")
    blocked = ingest_path(pdf, **kw)
    assert blocked.action == "blocked"
    assert "printed_total" in (blocked.gap or "")
    assert load_rows(cwg) == []
    written = ingest_path(
        pdf, override_reason="unitemized LTL freight is cash that left the account", **kw
    )
    assert written.action == "appended"
    rows = load_rows(cwg)
    assert len(rows) == 1
    assert rows[0]["amount_usd"] == "127.16"
    log = changes_path(cwg).read_text(encoding="utf-8")
    assert "unitemized LTL freight" in log


def test_amend_with_audit_trail(tmp_path: Path):
    from soveryn.platform.ledgers.books import amend_row

    book = tmp_path / "book.csv"
    row = append_row(
        book,
        {
            "tax_year": "2026",
            "date": "2026-10-03",
            "vendor": "Acme",
            "description": "widget",
            "schedule_c_or_form": "supplies",
            "amount_usd": "10.00",
            "status": "DOCUMENTED",
            "payment_method": "",
            "evidence": "evidence/2026/widget.pdf",
            "notes": "",
        },
        actor="test",
        reason="seed",
    )
    edited = amend_row(
        book,
        row["row_id"],
        reason="correct vendor spelling",
        updates={"vendor": "Acme LLC"},
        actor="ledger_amend",
    )
    assert edited["ok"] is True
    assert edited["action"] == "edited"
    assert load_rows(book)[0]["vendor"] == "Acme LLC"
    removed = amend_row(
        book,
        row["row_id"],
        reason="duplicate of later filing",
        remove=True,
        actor="ledger_amend",
    )
    assert removed["ok"] is True
    assert removed["action"] == "removed"
    assert load_rows(book) == []
    archive = Path(str(removed["archive"]))
    assert archive.is_file()
    assert archive.name.startswith("duplicates-removed-")
    assert "Acme LLC" in archive.read_text(encoding="utf-8")
    log_lines = [
        json.loads(line)
        for line in changes_path(book).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    actions = [item["action"] for item in log_lines]
    assert "edit" in actions
    assert "remove" in actions
    assert any(item["reason"] == "correct vendor spelling" for item in log_lines)


def test_reconcile_output(tmp_path: Path):
    from soveryn.platform.ledgers.reconcile import audit_books

    book = tmp_path / "book.csv"
    ev = tmp_path / "evidence"
    (ev / "2026").mkdir(parents=True)
    (ev / "2026" / "kept.pdf").write_bytes(b"same-bytes")
    (ev / "2026" / "orphan.pdf").write_bytes(b"orphan")
    append_row(
        book,
        {
            "tax_year": "2026",
            "date": "2026-10-03",
            "vendor": "Acme",
            "description": "one (order 9999)",
            "schedule_c_or_form": "supplies",
            "amount_usd": "10.00",
            "status": "DOCUMENTED",
            "payment_method": "",
            "evidence": "evidence/2026/kept.pdf",
            "notes": "",
            "order_id": "9999",
            "evidence_sha256": "abc",
        },
        actor="test",
        reason="seed-a",
    )
    append_row(
        book,
        {
            "tax_year": "2026",
            "date": "2026-10-03",
            "vendor": "Acme",
            "description": "two (order 9999)",
            "schedule_c_or_form": "supplies",
            "amount_usd": "10.00",
            "status": "DOCUMENTED",
            "payment_method": "",
            "evidence": "evidence/2026/missing.pdf",
            "notes": "",
            "order_id": "9999",
            "evidence_sha256": "abc",
        },
        actor="test",
        reason="seed-b",
    )
    report = audit_books({"cwg": book}, {"cwg": ev})
    cwg = report["books"][0]
    assert cwg["rows"] == 2
    assert cwg["total_usd"] == "20.00"
    assert cwg["counts"]["missing_evidence"] == 1
    assert cwg["counts"]["unreferenced_evidence"] == 1
    kinds = {item["kind"] for item in cwg["duplicates"]}
    assert "order_id" in kinds
    assert "evidence_sha256" in kinds
    assert "date_vendor_amount" in kinds
    assert report["read_only"] is True


def test_old_format_book_without_new_columns(tmp_path: Path):
    book = tmp_path / "old.csv"
    header = ",".join(LEGACY_FIELDS) + "\r\n"
    body = (
        "2026,2026-10-01,OldCo,legacy row,supplies,3.50,DOCUMENTED,,"
        "evidence/2026/old.pdf,note only\n"
    )
    book.write_bytes((header + body).encode("utf-8"))
    rows = load_rows(book)
    assert len(rows) == 1
    assert rows[0]["vendor"] == "OldCo"
    assert rows[0]["row_id"] == ""
    assert rows[0]["evidence_sha256"] == ""
    assert rows[0]["printed_total"] == ""
    raw = book.read_bytes()
    assert b"\r\n" in raw and b"note only\n" in raw

    pdf = tmp_path / "new.pdf"
    pdf.write_bytes(b"%PDF-old-format")
    result = ingest_path(
        pdf,
        books={"soveryn": tmp_path / "s.csv", "cwg": book},
        evidence_roots={"soveryn": tmp_path / "ev-s", "cwg": tmp_path / "ev-c"},
        extract=lambda _p: _extract(AMAZON_CWG, "new.pdf"),
        book="cwg",
    )
    assert result.action == "appended"
    after = load_rows(book)
    assert len(after) == 2
    assert after[0]["vendor"] == "OldCo"
    leftover = book.read_bytes()
    assert b"legacy row" in leftover


def test_migrate_ledger_columns_dry_run_then_apply(tmp_path: Path):
    from scripts.migrate_ledger_columns import apply_migration, plan_migration

    book = tmp_path / "old.csv"
    ev = tmp_path / "evidence" / "2026"
    ev.mkdir(parents=True)
    blob = b"synthetic-evidence-bytes"
    (ev / "old.pdf").write_bytes(blob)
    book.write_text(
        ",".join(LEGACY_FIELDS)
        + "\n"
        + "2026,2026-10-01,OldCo,legacy row,supplies,3.50,DOCUMENTED,,"
        + "evidence/2026/old.pdf,note only\n",
        encoding="utf-8",
    )
    before = book.read_bytes()
    plan = plan_migration(book)
    assert "row_id" in plan["missing_columns"]
    assert plan["row_ids_to_fill"] == 1
    assert plan["hashes_to_fill"] == 1
    assert book.read_bytes() == before
    apply_migration(book, plan)
    rows = load_rows(book)
    assert rows[0]["row_id"]
    assert rows[0]["evidence_sha256"]
    assert rows[0]["vendor"] == "OldCo"
    header = book.read_text(encoding="utf-8").splitlines()[0]
    assert header.endswith("printed_total")
    assert "row_id" in header


def test_write_book_is_single_writer(tmp_path: Path):
    book = tmp_path / "book.csv"
    write_book(
        book,
        [
            {
                "tax_year": "2026",
                "date": "2026-10-03",
                "vendor": "Solo",
                "description": "one",
                "schedule_c_or_form": "supplies",
                "amount_usd": "1.00",
                "status": "DOCUMENTED",
                "payment_method": "",
                "evidence": "",
                "notes": "",
            }
        ],
        actor="test",
        changes=[],
        reason="create",
    )
    backups = list(tmp_path.glob("book.csv.bak-*"))
    # first create has no prior bytes, so no backup required
    assert load_rows(book)[0]["vendor"] == "Solo"
    append_row(
        book,
        {
            "tax_year": "2026",
            "date": "2026-10-03",
            "vendor": "Two",
            "description": "two",
            "schedule_c_or_form": "supplies",
            "amount_usd": "2.00",
            "status": "DOCUMENTED",
            "payment_method": "",
            "evidence": "",
            "notes": "",
        },
        actor="test",
        reason="second",
    )
    backups = list(tmp_path.glob("book.csv.bak-*"))
    assert backups
    log = changes_path(book).read_text(encoding="utf-8")
    assert "second" in log
