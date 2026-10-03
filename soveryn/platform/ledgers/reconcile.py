"""Ledger reconciliation — catch bookkeeping drift weekly, not at tax time.

Checks both expense books (CWG + SOVERYN) against their evidence trees and
reports four defect classes:

  1. ORPHAN_EVIDENCE   file in evidence/ that no ledger row points at
  2. MISSING_EVIDENCE  row marked DOCUMENTED whose evidence file does not exist
  3. PROSE_EVIDENCE    DOCUMENTED row whose evidence column is prose/a to-do
                       note rather than a path under evidence/
  4. OPEN_AGING        rows stuck in NEED_INVOICE / NEED_EXPORT / other
                       non-DOCUMENTED status longer than ``open_days``

Design rule (verification spirit): DOCUMENTED must mean "a real file exists
and the row points at it". Everything else is drift this module names.

CLI:  python -m soveryn.platform.ledgers.reconcile [--json] [--open-days N]
      python -m soveryn.platform.ledgers.reconcile --notify   # timer mode:
      writes docs/ops/tax/RECONCILE-LATEST.md and webpushes Jon on drift.
Exit code 0 = clean, 1 = drift found (so cron/systemd can alert on it).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

from .books import load_rows
from .paths import cwg_csv, evidence_root, repo_root, soveryn_csv

DOCUMENTED = "DOCUMENTED"
DEFAULT_OPEN_DAYS = 10

# Folders under evidence/ that are archives, not live shelf. Shared so
# check_book / check_all and audit_books / ledger_reconcile cannot drift.
EVIDENCE_ARCHIVE_FOLDERS: frozenset[str] = frozenset({"superseded", "duplicates"})


def _parse_row_date(raw: str) -> date | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _in_archive_folder(rel: str) -> bool:
    """True when any path segment is an evidence archive folder."""
    return any(part in EVIDENCE_ARCHIVE_FOLDERS for part in Path(rel).parts)


def _evidence_files(root: Path) -> tuple[dict[str, Path], int]:
    """Live relative-path -> file, plus a count of archived-folder files.

    Ignores README notes and archive subtrees listed in
    ``EVIDENCE_ARCHIVE_FOLDERS`` (superseded/ and duplicates/). Everything
    else is "on the shelf" and must be referenced by a row.
    """
    out: dict[str, Path] = {}
    archived = 0
    if not root.is_dir():
        return out, archived
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root.parent).as_posix()
        if p.name.upper().startswith("README"):
            continue
        if _in_archive_folder(rel):
            archived += 1
            continue
        out[rel] = p
    return out, archived


def _is_evidence_path(raw: str) -> bool:
    """True when the evidence column actually names a file under evidence/."""
    raw = (raw or "").strip()
    return bool(raw) and raw.startswith("evidence/") and not raw.endswith((".html", ".md"))


def check_book(csv_path: Path, *, open_days: int = DEFAULT_OPEN_DAYS, today: date | None = None) -> dict[str, Any]:
    """Reconcile one book. Returns {book, defects, counts}."""
    today = today or date.today()
    root = csv_path.parent
    ev_root = evidence_root(csv_path.stem.split("-")[0].replace("CWG", "cwg").lower(), repo_root())
    # evidence_root keys off book name; resolve directly from the csv location
    # instead so a renamed csv never points the check at the wrong tree.
    ev_root = root / "evidence"

    rows = load_rows(csv_path)

    on_disk, archived_n = _evidence_files(ev_root)
    referenced: set[str] = set()

    missing: list[dict[str, str]] = []
    prose: list[dict[str, str]] = []
    open_aging: list[dict[str, str]] = []
    open_planning: list[dict[str, str]] = []

    for r in rows:
        ev = (r.get("evidence") or "").strip()
        status = (r.get("status") or "").strip().upper()
        if _is_evidence_path(ev):
            referenced.add(ev)
            if status == DOCUMENTED and not (root / ev).is_file():
                missing.append({"date": r.get("date", ""), "vendor": r.get("vendor", ""), "evidence": ev})
        elif status == DOCUMENTED and ev:
            prose.append({"date": r.get("date", ""), "vendor": r.get("vendor", ""), "evidence": ev[:80]})

        if status and status != DOCUMENTED and status not in ("EXCLUDE",):
            d = _parse_row_date(r.get("date", ""))
            age = (today - d).days if d else None
            item = {
                "date": r.get("date", "") or "undated",
                "vendor": r.get("vendor", ""),
                "description": (r.get("description") or "")[:60],
                "status": status,
                "age_days": age,
            }
            # Dated open rows age against the calendar and escalate.
            # Undated rows are standing planning lines; they surface in the
            # report but never pretend to be "aging".
            if age is not None and age > open_days:
                open_aging.append(item)
            elif age is None:
                open_planning.append(item)

    orphans = sorted(set(on_disk) - referenced)

    return {
        "book": csv_path.name,
        "csv": str(csv_path),
        "rows": len(rows),
        "evidence_files": len(on_disk),
        "archived_evidence_files": archived_n,
        "defects": {
            "ORPHAN_EVIDENCE": [{"evidence": f} for f in orphans],
            "MISSING_EVIDENCE": missing,
            "PROSE_EVIDENCE": prose,
            "OPEN_AGING": open_aging,
            "OPEN_PLANNING": open_planning,
        },
        "counts": {
            k: len(v)
            for k, v in (
                ("ORPHAN_EVIDENCE", orphans),
                ("MISSING_EVIDENCE", missing),
                ("PROSE_EVIDENCE", prose),
                ("OPEN_AGING", open_aging),
                ("OPEN_PLANNING", open_planning),
            )
        },
    }


def check_all(*, root: Path | None = None, open_days: int = DEFAULT_OPEN_DAYS, today: date | None = None) -> dict[str, Any]:
    root = root or repo_root()
    books = [
        check_book(cwg_csv(root), open_days=open_days, today=today),
        check_book(soveryn_csv(root), open_days=open_days, today=today),
    ]
    total = sum(sum(b["counts"].values()) for b in books)
    return {"checked_at": datetime.now().isoformat(timespec="seconds"), "clean": total == 0, "total_defects": total, "books": books}


def _amount_total(rows: list[dict[str, str]]) -> str:
    total = Decimal("0.00")
    for row in rows:
        raw = (row.get("amount_usd") or "").replace("$", "").replace(",", "").strip()
        if not raw:
            continue
        try:
            total += Decimal(raw)
        except InvalidOperation:
            continue
    return f"{total.quantize(Decimal('0.01'))}"


def _dup_groups(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        digest = (row.get("evidence_sha256") or "").strip().lower()
        if digest:
            groups[("evidence_sha256", digest)].append(row)
        oid = (row.get("order_id") or "").strip()
        if oid:
            groups[("order_id", oid)].append(row)
        key = (
            (row.get("date") or "").strip(),
            (row.get("vendor") or "").strip().lower(),
            (row.get("amount_usd") or "").strip(),
        )
        if all(key):
            groups[("date_vendor_amount", "|".join(key))].append(row)
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for (kind, value), members in groups.items():
        if len(members) < 2:
            continue
        ids = tuple(sorted((m.get("row_id") or "") for m in members))
        stamp = (kind, ids)
        if stamp in seen:
            continue
        seen.add(stamp)
        out.append(
            {
                "kind": kind,
                "value": value,
                "count": len(members),
                "row_ids": [m.get("row_id", "") for m in members],
                "amounts": [m.get("amount_usd", "") for m in members],
            }
        )
    return out


def audit_books(
    books: Mapping[str, Path],
    evidence_roots: Mapping[str, Path] | None = None,
) -> dict[str, Any]:
    """Read-only report: duplicates, missing evidence, orphans, counts/totals."""
    ev_roots = evidence_roots or {}
    reports: list[dict[str, Any]] = []
    for book_id, csv_path in sorted(books.items()):
        csv_path = Path(csv_path)
        rows = load_rows(csv_path)
        ev_root = Path(ev_roots.get(book_id) or (csv_path.parent / "evidence"))
        on_disk, archived_n = _evidence_files(ev_root)
        referenced: set[str] = set()
        missing: list[dict[str, str]] = []
        for row in rows:
            ev = (row.get("evidence") or "").strip()
            if not _is_evidence_path(ev):
                continue
            referenced.add(ev)
            rel = ev[len("evidence/") :] if ev.startswith("evidence/") else ev
            disk = ev_root / rel
            beside = csv_path.parent / ev
            if not disk.is_file() and not beside.is_file():
                missing.append(
                    {
                        "row_id": row.get("row_id", ""),
                        "date": row.get("date", ""),
                        "vendor": row.get("vendor", ""),
                        "evidence": ev,
                    }
                )
        orphans = sorted(set(on_disk) - referenced)
        duplicates = _dup_groups(rows)
        reports.append(
            {
                "book": book_id,
                "csv": str(csv_path),
                "rows": len(rows),
                "total_usd": _amount_total(rows),
                "evidence_files": len(on_disk),
                "archived_evidence_files": archived_n,
                "duplicates": duplicates,
                "missing_evidence": missing,
                "unreferenced_evidence": [{"evidence": f} for f in orphans],
                "counts": {
                    "rows": len(rows),
                    "duplicates": len(duplicates),
                    "missing_evidence": len(missing),
                    "unreferenced_evidence": len(orphans),
                    "archived_evidence": archived_n,
                },
            }
        )
    return {
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "read_only": True,
        "books": reports,
    }


def format_report(report: dict[str, Any]) -> str:
    """Human-readable text for Signal/CC inbox/file.

    Accepts the full check_all() report or a single check_book() result.
    """
    if "books" not in report:
        report = {
            "clean": sum(report["counts"].values()) == 0,
            "total_defects": sum(report["counts"].values()),
            "books": [report],
        }
    lines: list[str] = []
    if report["clean"]:
        return "Ledger reconcile: clean. Evidence and books agree; no open items aging."
    lines.append(f"Ledger drift: {report['total_defects']} item(s). Fix before these age into tax season.")
    for b in report["books"]:
        d = b["defects"]
        if not any(d.values()):
            continue
        lines.append(f"\n[{b['book']}] rows={b['rows']} evidence={b['evidence_files']}")
        for f in d["ORPHAN_EVIDENCE"]:
            lines.append(f"  ORPHAN (filed, not booked): {f['evidence']}")
        for f in d["MISSING_EVIDENCE"]:
            lines.append(f"  MISSING (booked, file gone): {f['date']} {f['vendor']} -> {f['evidence']}")
        for f in d["PROSE_EVIDENCE"]:
            lines.append(f"  PROSE (DOCUMENTED but evidence is a note): {f['date']} {f['vendor']} -> {f['evidence']}")
        for f in d["OPEN_AGING"]:
            lines.append(f"  OPEN ({f['status']}, age {f['age_days']}d): {f['date']} {f['vendor']} {f['description']}")
        if d["OPEN_PLANNING"]:
            lines.append(f"  planning lines (undated, {len(d['OPEN_PLANNING'])}): " + "; ".join(f"{p['vendor']} {p['description'][:30]}" for p in d["OPEN_PLANNING"]))
    return "\n".join(lines)


def _notify_drift(report: dict[str, Any]) -> None:
    """Write the latest report next to the books and push Jon's phone.

    Fire-and-forget: a failed push must never fail the reconcile itself.
    """
    logger = logging.getLogger(__name__)
    out = repo_root() / "docs" / "ops" / "tax" / "RECONCILE-LATEST.md"
    try:
        out.write_text(
            f"# Ledger reconcile — {report['checked_at']}\n\n"
            + format_report(report)
            + "\n",
            encoding="utf-8",
        )
    except OSError:
        logger.exception("reconcile: could not write %s", out)
    try:
        from soveryn.platform.webpush.notify import notify_needs_you

        notify_needs_you(
            title=f"Ledger drift: {report['total_defects']} item(s)",
            body="Receipt books vs evidence disagree. See RECONCILE-LATEST.",
            url="/messages",
            tag="ledger-reconcile",
        )
    except Exception:
        logger.exception("reconcile: webpush failed")


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ledger-reconcile")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of text")
    ap.add_argument("--notify", action="store_true", help="timer mode: write RECONCILE-LATEST.md + webpush on drift")
    ap.add_argument("--open-days", type=int, default=DEFAULT_OPEN_DAYS)
    args = ap.parse_args(argv)
    report = check_all(open_days=args.open_days)
    if args.notify:
        if report["clean"]:
            # Refresh the report file so "last checked" stays current.
            _notify_drift(report)
        else:
            _notify_drift(report)
    if args.json:
        print(json.dumps(report, indent=1))
    else:
        print(format_report(report))
    return 0 if report["clean"] else 1


if __name__ == "__main__":
    sys.exit(_main())
