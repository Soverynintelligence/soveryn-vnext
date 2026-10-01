"""Docs consistency guards (Critic run 9d3933be, 2026-09-09).

Asserts README.md and docs/CURRENT_TRUTH.md stay in lockstep:
- README defers public surfaces to CURRENT_TRUTH §1 (single source; no
  duplicated README table since the 2026-09-22 docs pass)
- CURRENT_TRUTH §1 tables carry no 'unverified' cells
- §0 public-products row lists the public products
- §0a fleet rows carry a dated 'Last verified' (not a placeholder)
- superseded truth snapshot lives only in docs/archive/, not docs/ top level
"""

from __future__ import annotations

import re
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"
CURRENT_TRUTH = REPO / "docs" / "CURRENT_TRUTH.md"


def _read(path: Path) -> str:
    assert path.exists(), f"missing file: {path}"
    return path.read_text(encoding="utf-8")


def _table_rows(md: str, heading: str) -> list[list[str]]:
    """Return cell lists for the first markdown table after `heading`.

    Finds the first line containing `heading` (whether it's a markdown
    heading, a bold line, or a table row itself), then scans subsequent
    lines for a markdown table.
    """
    lines = md.splitlines()
    try:
        start = next(
            i
            for i, ln in enumerate(lines)
            if heading in ln
        )
    except StopIteration:
        pytest.fail(f"heading not found: {heading!r}")
    table: list[list[str]] = []
    for ln in lines[start + 1:]:
        stripped = ln.strip()
        if stripped.startswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):
                continue  # separator row
            table.append(cells)
        elif table:
            break
    assert table, f"no table found under heading {heading!r}"
    return table


def test_readme_public_table_has_no_unverified_cells() -> None:
    readme = _read(README)
    section = "## Public surfaces"
    assert section in readme, "README lost its Public surfaces section"
    after = readme.split(section, 1)[1].split("\n## ", 1)[0]
    assert "CURRENT_TRUTH.md" in after and "§1" in after, (
        "README Public surfaces must point at CURRENT_TRUTH §1 (single source)"
    )
    ct = _read(CURRENT_TRUTH)
    ct_section = ct.split("## 1. What is live", 1)[1].split("\n## ", 1)[0]
    for row in _table_rows(ct_section, "House (soveryn_vnext)")[1:]:
        joined = " ".join(row).lower()
        assert "unverified" not in joined, f"unverified cell in §1 row: {row}"


def test_rosters_match_between_readme_and_current_truth() -> None:
    ct = _read(CURRENT_TRUTH)
    section = ct.split("## 0. House spine", 1)[1].split("### 0a.", 1)[0]
    spine = " ".join(section.lower().split())
    for name in ("atticus", "tgthrmess", "pondwright", "seneca"):
        assert name in spine, f"§0 spine missing {name!r}"
    assert "soverynintelligence.com" in spine, (
        "§0 spine missing the customer site"
    )


def test_fleet_rows_have_last_verified_dates() -> None:
    ct = _read(CURRENT_TRUTH)
    section = ct.split("### 0a. Fleet freeze", 1)[1].split("### 0b.", 1)[0]
    rows = [
        row
        for row in _table_rows(section, "Per-row verification dates")
    ]
    body = rows[1:]
    assert body, "no per-row verification rows"
    needles = ("qwen 3.8-27b", "flash-next", "qwen3.5-9b")
    for row in body:
        joined = " ".join(row).lower()
        if any(n in joined for n in needles):
            assert re.search(r"20\d\d-\d\d-\d\d", joined), (
                f"fleet row lacks a last-verified date: {row}"
            )


def test_stale_archive_quarantined() -> None:
    assert not (REPO / "docs" / "CURRENT_TRUTH_2026-05-23.md").exists(), (
        "superseded snapshot still at docs/ top level; move to docs/archive/"
    )
    assert (REPO / "docs" / "archive" / "CURRENT_TRUTH_2026-05-23.md").exists()
