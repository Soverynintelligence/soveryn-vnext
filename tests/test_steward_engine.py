"""Tests for soveryn.platform.steward.engine — deterministic grant-compliance schedule.
Pure datetime arithmetic; no LLM, no DB, no network.
"""

from datetime import date
from soveryn.platform.steward.engine import Grant, compute_grant_schedule


def _annual_grant():
    return Grant(funder="Cosmos Institute", award_id="COSMOS-1", title="Sovereign AI",
                 period_start=date(2025, 9, 1), period_end=date(2027, 8, 31),
                 reporting_cadence="annual")


def test_annual_reports_on_each_anniversary_in_window():
    obs = compute_grant_schedule([_annual_grant()], today=date(2026, 6, 27),
                                 lookback_days=365, horizon_days=365)
    dues = sorted(o.due_date for o in obs)
    # annual report due on each period anniversary within the window (PROVISIONAL — verify per award)
    assert date(2026, 9, 1) in dues            # upcoming anniversary
    assert all(o.award_id == "COSMOS-1" and o.funder == "Cosmos Institute" for o in obs)


def test_overdue_vs_upcoming_status():
    obs = compute_grant_schedule([_annual_grant()], today=date(2026, 6, 27),
                                 lookback_days=365, horizon_days=365)
    for o in obs:
        assert o.status == ("overdue" if o.due_date < date(2026, 6, 27) else "upcoming")


def test_milestone_cadence_materializes_each_milestone():
    g = Grant(funder="NSF", award_id="NSF-9", title="Phase I",
              period_start=date(2026, 1, 1), period_end=date(2027, 1, 1),
              reporting_cadence="milestone",
              milestones=(("2026-06-30", "Prototype report"), ("2026-12-31", "Phase I final")))
    obs = compute_grant_schedule([g], today=date(2026, 6, 27), lookback_days=365, horizon_days=365)
    dues = {o.due_date for o in obs}
    assert date(2026, 6, 30) in dues and date(2026, 12, 31) in dues


def test_final_report_after_period_end():
    g = Grant(funder="X", award_id="X-1", title="t", period_start=date(2025, 1, 1),
              period_end=date(2026, 7, 1), reporting_cadence="final")
    obs = compute_grant_schedule([g], today=date(2026, 6, 27), lookback_days=0, horizon_days=365)
    # final report due FINAL_OFFSET_DAYS after period_end (PROVISIONAL)
    assert any(o.due_date > date(2026, 7, 1) for o in obs)


def test_sorted_by_due_date():
    """Output must be sorted ascending by due_date regardless of grant input order."""
    g1 = Grant(funder="A", award_id="A-1", title="t1", period_start=date(2025, 1, 1),
               period_end=date(2027, 1, 1), reporting_cadence="annual")
    g2 = Grant(funder="B", award_id="B-2", title="t2", period_start=date(2025, 6, 1),
               period_end=date(2027, 6, 1), reporting_cadence="annual")
    obs = compute_grant_schedule([g2, g1], today=date(2026, 6, 27),
                                 lookback_days=365, horizon_days=365)
    dates = [o.due_date for o in obs]
    assert dates == sorted(dates)


def test_empty_grants_returns_empty():
    obs = compute_grant_schedule([], today=date(2026, 6, 27), lookback_days=365, horizon_days=365)
    assert obs == []


def test_quarterly_cadence_emits_quarterly_dates():
    g = Grant(funder="Q", award_id="Q-1", title="qgrant",
              period_start=date(2026, 1, 1), period_end=date(2027, 1, 1),
              reporting_cadence="quarterly")
    obs = compute_grant_schedule([g], today=date(2026, 6, 27), lookback_days=180, horizon_days=180)
    dues = {o.due_date for o in obs}
    # Q1=2026-04-01, Q2=2026-07-01, Q3=2026-10-01 should appear within window
    assert date(2026, 4, 1) in dues
    assert date(2026, 7, 1) in dues


def test_obligation_fields_are_populated():
    obs = compute_grant_schedule([_annual_grant()], today=date(2026, 6, 27),
                                 lookback_days=365, horizon_days=365)
    assert obs  # at least one obligation
    o = obs[0]
    assert o.award_id == "COSMOS-1"
    assert o.funder == "Cosmos Institute"
    assert o.title == "Sovereign AI"
    assert o.report_label  # non-empty
    assert isinstance(o.due_date, date)
    assert o.status in ("upcoming", "overdue")
