"""Ledger reconciliation checks — DOCUMENTED must mean a real file exists."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

import pytest

from soveryn.platform.ledgers.reconcile import (
    EVIDENCE_ARCHIVE_FOLDERS,
    audit_books,
    check_book,
    format_report,
)


@pytest.fixture()
def book(tmp_path: Path) -> Path:
    root = tmp_path / "book"
    (root / "evidence" / "2026").mkdir(parents=True)
    (root / "evidence" / "superseded").mkdir(parents=True)
    return root


def _csv(root: Path, rows: list[dict[str, str]]) -> Path:
    path = root / "LEDGER.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return path


def _row(**over) -> dict[str, str]:
    r = {
        "date": "2026-09-01",
        "vendor": "Acme",
        "description": "thing",
        "amount_usd": "10.00",
        "status": "DOCUMENTED",
        "evidence": "",
        "notes": "",
    }
    r.update(over)
    return r


def test_clean_book(book: Path):
    (book / "evidence" / "2026" / "2026-09-01_acme_thing_10.00.pdf").write_text("x")
    p = _csv(book, [_row(evidence="evidence/2026/2026-09-01_acme_thing_10.00.pdf")])
    rep = check_book(p)
    assert rep["counts"] == {"ORPHAN_EVIDENCE": 0, "MISSING_EVIDENCE": 0, "PROSE_EVIDENCE": 0, "OPEN_AGING": 0, "OPEN_PLANNING": 0}


def test_orphan_and_missing(book: Path):
    (book / "evidence" / "2026" / "orphan.pdf").write_text("x")
    p = _csv(
        book,
        [
            _row(evidence="evidence/2026/orphan.pdf"),  # not referenced below
            _row(vendor="Ghost", evidence="evidence/2026/ghost.pdf"),
        ],
    )
    rep = check_book(p)
    # orphan.pdf is referenced by row 1, so the orphan is row 2's ghost
    assert rep["counts"]["MISSING_EVIDENCE"] == 1
    assert rep["defects"]["MISSING_EVIDENCE"][0]["vendor"] == "Ghost"


def test_orphan_when_unreferenced(book: Path):
    (book / "evidence" / "2026" / "stray.pdf").write_text("x")
    p = _csv(book, [_row(evidence="")])
    rep = check_book(p)
    assert rep["counts"]["ORPHAN_EVIDENCE"] == 1
    assert "stray.pdf" in rep["defects"]["ORPHAN_EVIDENCE"][0]["evidence"]


def test_prose_evidence_flagged(book: Path):
    p = _csv(book, [_row(evidence="Downloads/CP_575_G.pdf")])
    rep = check_book(p)
    assert rep["counts"]["PROSE_EVIDENCE"] == 1


def test_superseded_and_readme_ignored(book: Path):
    (book / "evidence" / "superseded" / "old.pdf").write_text("x")
    (book / "evidence" / "README.txt").write_text("notes")
    p = _csv(book, [_row(evidence="")])
    rep = check_book(p)
    assert rep["counts"]["ORPHAN_EVIDENCE"] == 0
    assert "superseded" in EVIDENCE_ARCHIVE_FOLDERS
    assert "duplicates" in EVIDENCE_ARCHIVE_FOLDERS


def test_duplicates_folder_not_unreferenced_undated_still_is(book: Path):
    (book / "evidence" / "duplicates").mkdir(parents=True)
    (book / "evidence" / "undated").mkdir(parents=True)
    (book / "evidence" / "duplicates" / "copy.pdf").write_text("dup")
    (book / "evidence" / "undated" / "stray.pdf").write_text("stray")
    p = _csv(book, [_row(evidence="")])
    rep = check_book(p)
    orphans = [item["evidence"] for item in rep["defects"]["ORPHAN_EVIDENCE"]]
    assert not any("duplicates/" in ev for ev in orphans)
    assert any("undated/" in ev and "stray.pdf" in ev for ev in orphans)
    assert rep["counts"]["ORPHAN_EVIDENCE"] == 1
    assert rep["archived_evidence_files"] == 1

    audit = audit_books({"cwg": p}, {"cwg": book / "evidence"})
    unref = [item["evidence"] for item in audit["books"][0]["unreferenced_evidence"]]
    assert not any("duplicates/" in ev for ev in unref)
    assert any("undated/" in ev and "stray.pdf" in ev for ev in unref)
    assert audit["books"][0]["counts"]["unreferenced_evidence"] == 1
    assert audit["books"][0]["counts"]["archived_evidence"] == 1
    assert audit["books"][0]["archived_evidence_files"] == 1


def test_open_aging_uses_row_date(book: Path):
    p = _csv(
        book,
        [
            _row(status="NEED_INVOICE", evidence="", date="2026-01-01"),
            _row(status="NEED_EXPORT", evidence="", date=""),
            _row(status="EXCLUDE", evidence="", date="2026-01-01"),
        ],
    )
    rep = check_book(p, open_days=10, today=date(2026, 9, 18))
    assert rep["counts"]["OPEN_AGING"] == 1
    assert rep["counts"]["OPEN_PLANNING"] == 1
    assert rep["counts"]["OPEN_AGING_PLANNING" if False else "ORPHAN_EVIDENCE"] == 0


def test_exclude_row_skipped_in_total_and_duplicates(book: Path):
    (book / "evidence" / "2026" / "kept.pdf").write_text("kept")
    (book / "evidence" / "2026" / "excluded.pdf").write_text("excluded")
    path = _csv(
        book,
        [
            _row(
                vendor="OtherCo",
                amount_usd="4431.60",
                evidence="evidence/2026/kept.pdf",
                date="2026-09-01",
            ),
            _row(
                vendor="Cloudflare",
                amount_usd="10.46",
                evidence="evidence/2026/kept.pdf",
                date="2026-03-01",
                description="invoice IN75662012",
            ),
            _row(
                vendor="Cloudflare",
                amount_usd="10.46",
                status="EXCLUDE",
                evidence="evidence/2026/excluded.pdf",
                date="2026-03-01",
                description="invoice IN75664146",
            ),
        ],
    )
    audit = audit_books({"cwg": path}, {"cwg": book / "evidence"})
    cwg = audit["books"][0]
    assert cwg["rows"] == 3
    assert cwg["total_usd"] == "4452.52"
    assert cwg["counted_usd"] == "4442.06"
    assert cwg["excluded_rows"] == 1
    assert cwg["excluded_usd"] == "10.46"
    assert cwg["counts"]["excluded_rows"] == 1
    kinds = {item["kind"] for item in cwg["duplicates"]}
    assert "date_vendor_amount" not in kinds
    assert cwg["counts"]["duplicates"] == 0
    unref = [item["evidence"] for item in cwg["unreferenced_evidence"]]
    assert not any("excluded.pdf" in ev for ev in unref)
    assert cwg["counts"]["unreferenced_evidence"] == 0

    check = check_book(path)
    assert check["counts"]["ORPHAN_EVIDENCE"] == 0
    assert check["counts"]["OPEN_AGING"] == 0


def test_report_text_names_defects(book: Path):
    (book / "evidence" / "2026" / "stray.pdf").write_text("x")
    p = _csv(book, [_row(vendor="Ghost", evidence="evidence/2026/ghost.pdf")])
    text = format_report(check_book(p))
    assert "stray.pdf" in text and "Ghost" in text and "MISSING" in text
