"""Default locations for the two tax books and the intake drop folders."""

from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def soveryn_csv(root: Path | None = None) -> Path:
    base = root or repo_root()
    return base / "docs" / "ops" / "tax" / "SOVERYN-2025-2026-expense-ledger.csv"


def cwg_csv(root: Path | None = None) -> Path:
    base = root or repo_root()
    return base / "docs" / "ops" / "tax-cwg" / "CWG-2025-2026-expense-ledger.csv"


def evidence_root(book: str, root: Path | None = None) -> Path:
    base = root or repo_root()
    if book == "cwg":
        return base / "docs" / "ops" / "tax-cwg" / "evidence"
    return base / "docs" / "ops" / "tax" / "evidence"


def drop_root(root: Path | None = None) -> Path:
    base = root or repo_root()
    return base / "data" / "intake" / "ledgers"


def ensure_drop_dirs(root: Path | None = None) -> Path:
    drop = drop_root(root)
    for name in ("soveryn", "cwg", "unsorted"):
        (drop / name).mkdir(parents=True, exist_ok=True)
    return drop


def is_ledger_intake(path: Path) -> bool:
    """True for receipt drops under data/intake/ledgers/. Keep out of the KB."""
    parts = [p.lower() for p in Path(path).parts]
    try:
        i = parts.index("intake")
    except ValueError:
        return False
    return i + 1 < len(parts) and parts[i + 1] == "ledgers"
