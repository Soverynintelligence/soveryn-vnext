"""Bounded filing: Eve moves a Downloads/Desktop item into a named bucket.

Not a free mv. Source must be under Downloads or Desktop. Destination is one
of the house buckets. Never quotes, _incoming, or ledger CSVs. Never overwrite.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

_HOME = Path.home()

BUCKETS: dict[str, Path] = {
    "models": Path("/mnt/soveryn_models/GGUF"),
    "cwg_ig": _HOME / "Desktop" / "CWG-Instagram",
    "cwg_evidence": _HOME / "soveryn_vnext" / "docs" / "ops" / "tax-cwg" / "evidence",
    "cwg_insurance": _HOME / "soveryn_vnext" / "docs" / "ops" / "cwg-business" / "insurance",
    "cwg_licenses": _HOME / "soveryn_vnext" / "docs" / "ops" / "cwg-business" / "licenses",
    "cwg_vehicles": _HOME / "soveryn_vnext" / "docs" / "ops" / "cwg-business" / "vehicles",
    "cwg_contracts": _HOME / "soveryn_vnext" / "docs" / "ops" / "cwg-business" / "contracts",
    "soveryn_evidence": _HOME / "soveryn_vnext" / "docs" / "ops" / "tax" / "evidence",
    "pictures": _HOME / "Pictures",
    "installers": _HOME / "Downloads" / "installers",
}

_SRC_ROOTS: tuple[Path, ...] = (
    _HOME / "Downloads",
    _HOME / "Desktop",
)

_FORBIDDEN = (
    "quotes",
    "_incoming",
    "expense-ledger.csv",
    "SOVERYN-2025",
    "CWG-2025",
)

_MODELS_SUFFIXES = {".gguf"}


def bucket_paths() -> dict[str, str]:
    return {k: str(v) for k, v in BUCKETS.items()}


def file_away(
    src: str | Path,
    dest: str,
    *,
    src_roots: tuple[Path, ...] | None = None,
    buckets: dict[str, Path] | None = None,
) -> dict[str, Any]:
    """Move ``src`` into named bucket ``dest``. Returns ok/path/miss."""
    roots = src_roots if src_roots is not None else _SRC_ROOTS
    bucks = buckets if buckets is not None else BUCKETS
    raw = Path(str(src)).expanduser()
    if not str(dest).strip():
        return {"ok": False, "miss": "no_dest", "path": str(raw)}
    key = dest.strip().lower().replace("-", "_")
    if key not in bucks:
        return {
            "ok": False,
            "miss": "unknown_dest",
            "path": str(raw),
            "buckets": sorted(bucks),
        }
    try:
        resolved = raw.resolve()
    except OSError as exc:
        return {"ok": False, "miss": "unreadable", "path": str(raw), "error": str(exc)}
    if not _under_any(resolved, roots):
        return {"ok": False, "miss": "outside_source", "path": str(resolved)}
    if _forbidden(resolved):
        return {"ok": False, "miss": "forbidden", "path": str(resolved)}
    if not resolved.exists():
        return {"ok": False, "miss": "not_found", "path": str(resolved)}

    dest_dir = bucks[key].expanduser()
    if key == "models" and resolved.is_file() and resolved.suffix.lower() not in _MODELS_SUFFIXES:
        return {
            "ok": False,
            "miss": "not_a_model",
            "path": str(resolved),
            "hint": "models bucket takes .gguf only",
        }
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = (dest_dir / resolved.name).resolve()
    if not _under_any(target, (dest_dir.resolve(),)):
        return {"ok": False, "miss": "dest_escape", "path": str(resolved)}
    if target.exists():
        return {
            "ok": False,
            "miss": "already_there",
            "path": str(resolved),
            "dest": str(target),
        }
    shutil.move(str(resolved), str(target))
    return {
        "ok": True,
        "src": str(resolved),
        "dest": str(target),
        "bucket": key,
    }


def _under_any(path: Path, roots: tuple[Path, ...]) -> bool:
    for root in roots:
        try:
            path.relative_to(root.expanduser().resolve())
            return True
        except (ValueError, OSError):
            continue
    return False


def _forbidden(path: Path) -> bool:
    blob = path.as_posix().lower()
    return any(tok.lower() in blob for tok in _FORBIDDEN)
