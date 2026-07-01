"""Deterministic grant-compliance engine (the Shepherd pattern, grant domain).
Per-award: computes report deadlines from the grant's own terms. No LLM, never-guess.
Cadence constants are PROVISIONAL — verify each against the actual award letter.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

FINAL_OFFSET_DAYS = 90        # PROVISIONAL  # VERIFY per award letter (final report due N days after period_end)


@dataclass(frozen=True)
class Grant:
    funder: str
    award_id: str
    title: str
    period_start: date
    period_end: date
    reporting_cadence: str                  # "annual" | "quarterly" | "final" | "milestone"
    milestones: tuple[tuple[str, str], ...] = ()   # (iso_date, description)
    award_amount: float | None = None


@dataclass(frozen=True)
class GrantObligation:
    award_id: str
    funder: str
    title: str
    report_label: str
    due_date: date
    status: str                             # "upcoming" | "overdue" | "done" (set by store overlay)
    submitted_at: date | None = None        # populated by apply_submissions overlay
    note: str = ""                          # submission note, populated by apply_submissions overlay


def _add_months(d: date, months: int) -> date:
    """Add a whole number of months to a date, clamping to valid month-end days."""
    m = d.month - 1 + months
    y = d.year + m // 12
    mm = m % 12 + 1
    # clamp day to month length (handles Feb etc.)
    dd = min(d.day, calendar.monthrange(y, mm)[1])
    return date(y, mm, dd)


def _cadence_due_dates(g: Grant, start: date, end: date) -> list[tuple[date, str]]:
    """Return (due_date, report_label) pairs for the grant's cadence within [start, end].
    Cadence math is PROVISIONAL — verify against the actual award letter before relying on dates.
    """
    out: list[tuple[date, str]] = []
    if g.reporting_cadence == "annual":
        i = 1
        d = _add_months(g.period_start, 12)
        while d <= g.period_end:
            out.append((d, f"Annual report (year {i})"))
            i += 1
            d = _add_months(g.period_start, 12 * i)
    elif g.reporting_cadence == "quarterly":
        i = 1
        d = _add_months(g.period_start, 3)
        while d <= g.period_end:
            out.append((d, f"Quarterly report Q{i}"))
            i += 1
            d = _add_months(g.period_start, 3 * i)
    elif g.reporting_cadence == "final":
        out.append((g.period_end + timedelta(days=FINAL_OFFSET_DAYS), "Final report"))  # PROVISIONAL  # VERIFY per award letter
    elif g.reporting_cadence == "milestone":
        for iso, desc in g.milestones:
            out.append((date.fromisoformat(iso), desc or "Milestone"))
    # window filter
    return [(d, lbl) for (d, lbl) in out if start <= d <= end]


def compute_grant_schedule(
    grants: list[Grant],
    today: date,
    lookback_days: int,
    horizon_days: int,
) -> list[GrantObligation]:
    """Materialize report obligations for all grants within [today-lookback, today+horizon].

    Deterministic: same inputs always produce the same output.
    Status is "overdue" if due_date < today, else "upcoming".
    Returns obligations sorted ascending by due_date.
    """
    window_start = today - timedelta(days=lookback_days)
    window_end = today + timedelta(days=horizon_days)
    obligations: list[GrantObligation] = []
    for g in grants:
        for due, label in _cadence_due_dates(g, window_start, window_end):
            status = "overdue" if due < today else "upcoming"
            obligations.append(GrantObligation(
                award_id=g.award_id,
                funder=g.funder,
                title=g.title,
                report_label=label,
                due_date=due,
                status=status,
            ))
    return sorted(obligations, key=lambda o: o.due_date)
