"""Ledger reconciliation checks — DOCUMENTED must mean a real file exists."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

import pytest

from soveryn.platform.ledgers.reconcile import check_book, format_report


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


def test_report_text_names_defects(book: Path):
    (book / "evidence" / "2026" / "stray.pdf").write_text("x")
    p = _csv(book, [_row(vendor="Ghost", evidence="evidence/2026/ghost.pdf")])
    text = format_report(check_book(p))
    assert "stray.pdf" in text and "Ghost" in text and "MISSING" in text
