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
import csv
import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .paths import cwg_csv, evidence_root, repo_root, soveryn_csv

DOCUMENTED = "DOCUMENTED"
DEFAULT_OPEN_DAYS = 10


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


def _evidence_files(root: Path) -> dict[str, Path]:
    """Relative-path -> file for everything under a book's evidence tree.

    Ignores README notes and the superseded/ subtree (acknowledged
    duplicates kept for audit). Everything else is "on the shelf" and must
    be referenced by a row.
    """
    out: dict[str, Path] = {}
    if not root.is_dir():
        return out
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root.parent).as_posix()
        if p.name.upper().startswith("README") or "/superseded/" in f"/{rel}":
            continue
        out[rel] = p
    return out


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

    rows: list[dict[str, str]] = []
    if csv_path.is_file():
        with open(csv_path, newline="", encoding="utf-8") as fh:
            rows = [dict(r) for r in csv.DictReader(fh)]

    on_disk = _evidence_files(ev_root)
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
