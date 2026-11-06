#!/usr/bin/env python3
"""Verify the integrity checks declared in docs/CURRENT_TRUTH.md's header.

Mirrors the header's shell commands without shelling out to grep:

  section count:  grep -cE '^## [0-9]' docs/CURRENT_TRUTH.md  == 7
  row-date:       every table row that makes a status claim carries a
                  2026-YYYY-MM-DD date; header rows (the line immediately
                  followed by a separator row) are the only legal exception.
  header exclusion: header rows themselves must carry no 2026 date; this is
                  the check the old name-based grep exclusion silently passed.
  integrity footer: the last 10 non-empty lines must contain an
                  END-OF-TRUTH marker and an "Expected sections:" line whose
                  §N token count matches EXPECTED_SECTIONS.

Prints each result with its expected value and exits non-zero if any check
fails. Pass --json for a single machine-readable object instead.
"""
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TRUTH = REPO_ROOT / "docs" / "CURRENT_TRUTH.md"

SECTION_RE = re.compile(r"^## [0-9]")
DATE_RE = re.compile(r"2026-\d\d-\d\d")
EXPECTED_SECTIONS = 7
FOOTER_SECTION_RE = re.compile(r"§\d+")


def is_separator(line):
    """True if every cell is made only of '-', ':' or ' ' (a |---|:--| row)."""
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return bool(cells) and all(c and all(ch in "-: " for ch in c) for c in cells)


def main():
    if not TRUTH.is_file():
        print(f"missing file: {TRUTH}")
        return 1

    lines = TRUTH.read_text(encoding="utf-8").splitlines()

    sections = sum(1 for line in lines if SECTION_RE.match(line))
    section_pass = sections == EXPECTED_SECTIONS

    undated = []
    header_undated = []
    dates = []
    for i, line in enumerate(lines):
        if not line.startswith("|"):
            continue
        dates.extend(DATE_RE.findall(line))
        if is_separator(line):
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        is_header = nxt.startswith("|") and is_separator(nxt)
        if is_header:
            if not DATE_RE.search(line):
                header_undated.append(line)
            continue
        if not DATE_RE.search(line):
            undated.append(line)

    undated_pass = not undated
    header_pass = not header_undated
    newest = max(dates) if dates else None

    # Integrity footer check: last 10 non-empty lines.
    non_empty = [ln for ln in lines if ln.strip()]
    tail = non_empty[-10:]
    footer_present = any(ln.strip().startswith("END-OF-TRUTH") for ln in tail)
    footer_pass = footer_present

    footer_sections = None
    footer_sections_pass = False
    for ln in tail:
        if "Expected sections:" in ln:
            footer_sections = len(FOOTER_SECTION_RE.findall(ln))
            footer_sections_pass = footer_sections == EXPECTED_SECTIONS
            break

    ok = section_pass and undated_pass and header_pass and footer_pass and footer_sections_pass

    if "--json" in sys.argv:
        print(json.dumps({
            "section_count": sections,
            "section_expected": EXPECTED_SECTIONS,
            "section_pass": section_pass,
            "undated_rows": len(undated),
            "undated_pass": undated_pass,
            "header_undated": len(header_undated),
            "header_pass": header_pass,
            "newest_row_date": newest,
            "footer_present": footer_present,
            "footer_pass": footer_pass,
            "footer_sections": footer_sections,
            "footer_sections_pass": footer_sections_pass,
            "ok": ok,
        }))
    else:
        print(f"section count: {sections} (expected {EXPECTED_SECTIONS}) "
              f"{'PASS' if section_pass else 'FAIL'}")
        print(f"row-date undated: {len(undated)} (expected 0) "
              f"{'PASS' if undated_pass else 'FAIL'}")
        for line in undated[:10]:
            print(f"  {line[:120]}")
        print(f"header rows undated: {len(header_undated)} (expected 0) "
              f"{'PASS' if header_pass else 'FAIL'}")
        for line in header_undated[:10]:
            print(f"  {line[:120]}")
        print(f"newest row date: {newest if newest else '(none)'}")
        print(f"integrity footer: END-OF-TRUTH {'present' if footer_present else 'absent'} "
              f"{'PASS' if footer_pass else 'FAIL'}")
        print(f"footer section list: {footer_sections if footer_sections is not None else '(none)'} "
              f"(expected {EXPECTED_SECTIONS}) {'PASS' if footer_sections_pass else 'FAIL'}")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
