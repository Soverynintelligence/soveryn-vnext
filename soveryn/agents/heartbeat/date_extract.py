"""Date extraction helpers for the heartbeat deadline lane.

Pure functions — no wall-clock, no DB access. `now` is always injected
so tests are fully deterministic.

Supported formats:
  • Verbal month-day:  "June 30", "Jun 30" (± optional year e.g. "June 30, 2026")
  • ISO date:          "2026-06-30"
  • US slash M/D:      "06/30", "6/30" (assumes current/next year)
  • US slash M/D/Y:    "6/30/2026", "06/30/2026"

Roll-forward rule for ambiguous (year-less) dates:
  If the resolved date is more than ROLL_THRESHOLD_DAYS in the past,
  roll to the next calendar year so "June 30" near that date reads
  as "upcoming" rather than "360 days overdue".

Known limitations (defer — acceptable for English-first month-day/ISO nodes):
  (a) Ordinal + explicit year ("June 30th, 2026") loses the explicit year
      because _VERBAL_RE's opt_year group doesn't tolerate the ordinal suffix
      between the day digits and the year; falls back to year-resolution.
  (b) Day-first European format ("30 June 2026") can misparse — the verbal
      regex expects month-name before the day number.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Any

# Days-past threshold before we roll a year-less date to next year.
# "≤7 days past" is still treated as this-year (might be a fresh node
# created when the date was still upcoming). More than this → next year.
ROLL_THRESHOLD_DAYS = 7  # tune

# ── Month name lookup ──────────────────────────────────────────────────────────

_MONTH_NAMES: dict[str, int] = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}

# ── Regexes ───────────────────────────────────────────────────────────────────

# Verbal: "June 30" / "Jun 30" / "June 30, 2026" / "June 30 2026"
# Group names: month_name, day, opt_year
_VERBAL_RE = re.compile(
    r"\b(?P<month_name>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may"
    r"|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?"
    r"|nov(?:ember)?|dec(?:ember)?)"
    r"\s+(?P<day>\d{1,2})"
    r"(?:[,\s]+(?P<opt_year>\d{4}))?",
    re.IGNORECASE,
)

# ISO: "2026-06-30"
_ISO_RE = re.compile(r"\b(?P<iso_year>\d{4})-(?P<iso_month>\d{2})-(?P<iso_day>\d{2})\b")

# US slash with full year: "6/30/2026" or "06/30/2026"
_US_SLASH_FULL_RE = re.compile(r"\b(?P<sm>\d{1,2})/(?P<sd>\d{1,2})/(?P<sy>\d{4})\b")

# US slash without year: "06/30" or "6/30" — be careful not to grab the
# full-year variant; we apply this ONLY to matches NOT captured by _US_SLASH_FULL_RE.
# We use a negative look-ahead for a /YYYY suffix.
_US_SLASH_SHORT_RE = re.compile(
    r"\b(?P<sm>\d{1,2})/(?P<sd>\d{1,2})(?!/\d{4})\b"
)


def _resolve_year(month: int, day: int, now: date) -> date:
    """Resolve a year-less (month, day) to a specific date.

    If the resulting this-year date is more than ROLL_THRESHOLD_DAYS in the
    past, return next year's date instead.
    """
    try:
        candidate = date(now.year, month, day)
    except ValueError:
        return None  # invalid day (e.g. Feb 30)
    if (now - candidate).days > ROLL_THRESHOLD_DAYS:
        try:
            candidate = date(now.year + 1, month, day)
        except ValueError:
            return None
    return candidate


def extract_dates(text: str, now: date) -> list[date]:
    """Return all date-like strings found in `text`, resolved relative to `now`.

    Order: ISO first, then US-slash-full, then verbal, then US-slash-short
    (most-specific to least-specific so we don't double-count).
    Duplicates are de-duped; invalid day/month combinations are silently skipped.

    Args:
        text: free-form text (node content, title, etc.)
        now:  reference date for year-resolution; injected for determinism.

    Returns:
        List of unique date objects, sorted ascending. Empty list if none found.
    """
    results: set[date] = set()
    # Track char spans already claimed so shorter patterns don't double-match
    claimed: list[tuple[int, int]] = []

    def _overlaps(start: int, end: int) -> bool:
        return any(s < end and start < e for s, e in claimed)

    # 1. ISO dates — highest specificity
    for m in _ISO_RE.finditer(text):
        try:
            d = date(int(m.group("iso_year")), int(m.group("iso_month")), int(m.group("iso_day")))
            results.add(d)
            claimed.append((m.start(), m.end()))
        except ValueError:
            pass

    # 2. US slash full (M/D/YYYY) — before short-slash to avoid partial match
    for m in _US_SLASH_FULL_RE.finditer(text):
        if _overlaps(m.start(), m.end()):
            continue
        try:
            d = date(int(m.group("sy")), int(m.group("sm")), int(m.group("sd")))
            results.add(d)
            claimed.append((m.start(), m.end()))
        except ValueError:
            pass

    # 3. Verbal month-day (June 30 / Jun 30 [, 2026])
    for m in _VERBAL_RE.finditer(text):
        if _overlaps(m.start(), m.end()):
            continue
        month_str = m.group("month_name").lower()
        month = _MONTH_NAMES.get(month_str)
        if month is None:
            continue
        try:
            day = int(m.group("day"))
        except (TypeError, ValueError):
            continue
        if not (1 <= day <= 31):
            continue
        opt_year = m.group("opt_year")
        if opt_year:
            try:
                d = date(int(opt_year), month, day)
                results.add(d)
                claimed.append((m.start(), m.end()))
            except ValueError:
                pass
        else:
            d = _resolve_year(month, day, now)
            if d is not None:
                results.add(d)
                claimed.append((m.start(), m.end()))

    # 4. US slash short (M/D without year) — last, lowest precedence
    for m in _US_SLASH_SHORT_RE.finditer(text):
        if _overlaps(m.start(), m.end()):
            continue
        try:
            month = int(m.group("sm"))
            day = int(m.group("sd"))
        except (TypeError, ValueError):
            continue
        if not (1 <= month <= 12 and 1 <= day <= 31):
            continue
        d = _resolve_year(month, day, now)
        if d is not None:
            results.add(d)
            claimed.append((m.start(), m.end()))

    return sorted(results)


def build_dated_items(
    rows: list[Any],
    now: date,
) -> list[dict]:
    """Scan coordination node rows and return dated_items for detect_materiality.

    For each row:
      • If provenance has a 'deadline_date' ISO string, emit ONE non-fuzzy item
        for that date and skip regex scanning for that node.
      • Otherwise, run extract_dates on content and emit one fuzzy item per
        date found.

    Args:
        rows: list of row-like objects (sqlite3.Row or plain dict) with keys:
              id, content, provenance (JSON string).
        now:  reference date for year-resolution.

    Returns:
        List of dated_item dicts compatible with detect_materiality's
        dated_items parameter:
          {"ref": str, "detail": str, "date": date, "fuzzy": bool}
    """
    items: list[dict] = []

    for row in rows:
        # Support both sqlite3.Row and plain dict
        try:
            node_id = row["id"]
            content = row["content"] or ""
            prov_raw = row["provenance"] or "{}"
        except (KeyError, TypeError, IndexError):
            continue

        try:
            prov = json.loads(prov_raw)
        except (ValueError, TypeError):
            prov = {}

        # Title = first non-empty line, fallback to node id
        first_line = content.split("\n", 1)[0].strip()
        ref = first_line[:80] if first_line else node_id

        # Structured field takes precedence
        deadline_date_str = prov.get("deadline_date")
        if deadline_date_str:
            try:
                d = date.fromisoformat(str(deadline_date_str))
                items.append({
                    "ref": ref,
                    "detail": f"{ref} — structured deadline",
                    "date": d,
                    "fuzzy": False,
                })
                # Skip regex scan when structured date present
                continue
            except (ValueError, TypeError):
                pass  # fall through to regex

        # Regex scan
        found = extract_dates(content, now)
        for d in found:
            items.append({
                "ref": ref,
                "detail": f"{ref} — mentions {d.strftime('%B %-d')}",
                "date": d,
                "fuzzy": True,
            })

    return items
