"""Tests for soveryn.platform.steward.store — grants config loader, submission store, done-overlay.
Pure stdlib + steward engine only; no LLM, no DB network.
"""

import json
from datetime import date

import pytest

from soveryn.platform.steward.engine import GrantObligation
from soveryn.platform.steward.store import (
    StatusStore,
    SubmissionStore,
    apply_status_overrides,
    apply_submissions,
    load_grants,
    set_grant_status,
)


# ---------------------------------------------------------------------------
# StatusStore round-trip (manual applied/pending overrides, keyed by award_id)
# ---------------------------------------------------------------------------

def test_status_store_round_trip(tmp_path):
    s = StatusStore(str(tmp_path / "statuses.json"))
    s.set("COSMOS-1", "applied", note="submitted to funder portal")
    got = s.all()
    assert "COSMOS-1" in got
    assert got["COSMOS-1"]["status"] == "applied"
    assert got["COSMOS-1"]["note"] == "submitted to funder portal"
    assert got["COSMOS-1"]["set_at"]  # a date present


def test_status_store_persists_across_instances(tmp_path):
    path = str(tmp_path / "statuses.json")
    s1 = StatusStore(path)
    s1.set("NSF-9", "pending", note="awaiting info")
    s2 = StatusStore(path)
    got = s2.all()
    assert got["NSF-9"]["status"] == "pending"


def test_status_store_empty_initially(tmp_path):
    s = StatusStore(str(tmp_path / "new.json"))
    assert s.all() == {}


def test_status_store_clear_removes_override(tmp_path):
    s = StatusStore(str(tmp_path / "statuses.json"))
    s.set("COSMOS-1", "applied")
    s.clear("COSMOS-1")
    assert "COSMOS-1" not in s.all()


# ---------------------------------------------------------------------------
# apply_status_overrides — pure overlay, precedence done > manual > computed
# ---------------------------------------------------------------------------

def test_apply_status_overrides_marks_applied():
    obs = [GrantObligation("COSMOS-1", "Cosmos", "Sovereign AI", "Milestone",
                           date(2026, 1, 1), "overdue")]
    overrides = {"COSMOS-1": {"status": "applied", "note": "submitted"}}
    out = apply_status_overrides(obs, overrides)
    assert out[0].status == "applied"


def test_apply_status_overrides_marks_pending():
    obs = [GrantObligation("COSMOS-1", "Cosmos", "Sovereign AI", "Milestone",
                           date(2026, 1, 1), "overdue")]
    overrides = {"COSMOS-1": {"status": "pending", "note": ""}}
    out = apply_status_overrides(obs, overrides)
    assert out[0].status == "pending"


def test_apply_status_overrides_covers_all_obligations_of_grant():
    """A manual override is keyed by award_id and overlays every obligation."""
    obs = [
        GrantObligation("COSMOS-1", "Cosmos", "t", "M1", date(2026, 1, 1), "overdue"),
        GrantObligation("COSMOS-1", "Cosmos", "t", "M2", date(2027, 1, 1), "upcoming"),
    ]
    overrides = {"COSMOS-1": {"status": "applied", "note": ""}}
    out = apply_status_overrides(obs, overrides)
    assert [o.status for o in out] == ["applied", "applied"]


def test_apply_status_overrides_done_wins():
    """Precedence: a submission->done still wins over a manual applied/pending."""
    obs = [GrantObligation("COSMOS-1", "Cosmos", "t", "M1", date(2026, 1, 1), "done")]
    overrides = {"COSMOS-1": {"status": "applied", "note": ""}}
    out = apply_status_overrides(obs, overrides)
    assert out[0].status == "done"


def test_apply_status_overrides_leaves_unlisted():
    obs = [GrantObligation("X", "X", "t", "M", date(2026, 1, 1), "overdue")]
    assert apply_status_overrides(obs, {})[0].status == "overdue"


def test_apply_status_overrides_is_pure():
    obs = [GrantObligation("COSMOS-1", "Cosmos", "t", "M", date(2026, 1, 1), "overdue")]
    overrides = {"COSMOS-1": {"status": "applied", "note": ""}}
    apply_status_overrides(obs, overrides)
    assert obs[0].status == "overdue"


# ---------------------------------------------------------------------------
# set_grant_status — shared write path (tool + HTTP endpoint use this)
# ---------------------------------------------------------------------------

def test_set_grant_status_persists_and_round_trips(tmp_path):
    path = str(tmp_path / "statuses.json")
    res = set_grant_status(path, "COSMOS-1", "applied", note="portal ref 123")
    assert res["ok"] is True
    assert res["award_id"] == "COSMOS-1"
    assert res["status"] == "applied"
    # round-trips through a fresh store
    got = StatusStore(path).all()
    assert got["COSMOS-1"]["status"] == "applied"
    assert got["COSMOS-1"]["note"] == "portal ref 123"


def test_set_grant_status_rejects_invalid(tmp_path):
    path = str(tmp_path / "statuses.json")
    with pytest.raises(ValueError):
        set_grant_status(path, "COSMOS-1", "bogus")


def test_set_grant_status_clear_to_auto_restores(tmp_path):
    path = str(tmp_path / "statuses.json")
    set_grant_status(path, "COSMOS-1", "applied")
    res = set_grant_status(path, "COSMOS-1", "auto")
    assert res["ok"] is True
    assert res["status"] == "auto"
    assert "COSMOS-1" not in StatusStore(path).all()


def test_set_grant_status_empty_award_id_rejected(tmp_path):
    path = str(tmp_path / "statuses.json")
    with pytest.raises(ValueError):
        set_grant_status(path, "", "applied")


# ---------------------------------------------------------------------------
# SubmissionStore round-trip
# ---------------------------------------------------------------------------

def test_submission_round_trip(tmp_path):
    s = SubmissionStore(str(tmp_path / "subs.json"))
    s.record("COSMOS-1", date(2026, 9, 1), note="filed in research.gov")
    got = s.all()
    assert ("COSMOS-1", "2026-09-01") in got
    assert got[("COSMOS-1", "2026-09-01")]["submitted_at"]  # a date/iso present


def test_submission_store_rerecord_updates(tmp_path):
    """Re-recording the same obligation updates the entry rather than duplicating."""
    s = SubmissionStore(str(tmp_path / "subs.json"))
    s.record("COSMOS-1", date(2026, 9, 1), note="first")
    s.record("COSMOS-1", date(2026, 9, 1), note="updated")
    got = s.all()
    assert got[("COSMOS-1", "2026-09-01")]["note"] == "updated"
    # only one entry for that key
    assert len([k for k in got if k == ("COSMOS-1", "2026-09-01")]) == 1


def test_submission_store_persists_across_instances(tmp_path):
    """Data written by one SubmissionStore instance survives re-opening the file."""
    path = str(tmp_path / "subs.json")
    s1 = SubmissionStore(path)
    s1.record("NSF-9", date(2026, 6, 30), note="prototype")
    s2 = SubmissionStore(path)
    got = s2.all()
    assert ("NSF-9", "2026-06-30") in got


def test_submission_store_empty_initially(tmp_path):
    s = SubmissionStore(str(tmp_path / "new.json"))
    assert s.all() == {}


# ---------------------------------------------------------------------------
# apply_submissions — pure overlay
# ---------------------------------------------------------------------------

def test_apply_submissions_marks_done():
    obs = [GrantObligation("COSMOS-1", "Cosmos", "Sovereign AI", "Annual report (year 1)",
                           date(2026, 9, 1), "upcoming")]
    subs = {("COSMOS-1", "2026-09-01"): {"submitted_at": "2026-08-20", "note": ""}}
    out = apply_submissions(obs, subs)
    assert out[0].status == "done"


def test_apply_submissions_leaves_unsubmitted():
    obs = [GrantObligation("X", "X", "t", "Final report", date(2026, 10, 1), "overdue")]
    assert apply_submissions(obs, {})[0].status == "overdue"


def test_apply_submissions_carries_submitted_at():
    obs = [GrantObligation("COSMOS-1", "Cosmos", "Sovereign AI", "Annual report (year 1)",
                           date(2026, 9, 1), "upcoming")]
    subs = {("COSMOS-1", "2026-09-01"): {"submitted_at": "2026-08-20", "note": "on time"}}
    out = apply_submissions(obs, subs)
    assert out[0].submitted_at == date(2026, 8, 20)
    assert out[0].note == "on time"


def test_apply_submissions_is_pure():
    """apply_submissions must not mutate the input list or obligations."""
    obs = [GrantObligation("COSMOS-1", "Cosmos", "Sovereign AI", "Annual report (year 1)",
                           date(2026, 9, 1), "upcoming")]
    original_status = obs[0].status
    subs = {("COSMOS-1", "2026-09-01"): {"submitted_at": "2026-08-20", "note": ""}}
    apply_submissions(obs, subs)
    assert obs[0].status == original_status  # original untouched


def test_apply_submissions_mixed():
    """Only matching obligations flip to done; others preserve their status."""
    obs = [
        GrantObligation("COSMOS-1", "Cosmos", "Sovereign AI", "Annual report (year 1)",
                        date(2026, 9, 1), "upcoming"),
        GrantObligation("NSF-9", "NSF", "Phase I", "Prototype report",
                        date(2026, 6, 30), "overdue"),
    ]
    subs = {("COSMOS-1", "2026-09-01"): {"submitted_at": "2026-08-20", "note": ""}}
    out = apply_submissions(obs, subs)
    statuses = {o.award_id: o.status for o in out}
    assert statuses["COSMOS-1"] == "done"
    assert statuses["NSF-9"] == "overdue"


# ---------------------------------------------------------------------------
# load_grants
# ---------------------------------------------------------------------------

def test_load_grants_from_config(tmp_path):
    cfg = tmp_path / "grants.json"
    cfg.write_text(json.dumps([{
        "funder": "Cosmos Institute",
        "award_id": "COSMOS-1",
        "title": "Sovereign AI",
        "period_start": "2025-09-01",
        "period_end": "2027-08-31",
        "reporting_cadence": "annual",
    }]))
    grants = load_grants(str(cfg))
    assert grants[0].award_id == "COSMOS-1" and grants[0].reporting_cadence == "annual"


def test_load_grants_parses_dates(tmp_path):
    cfg = tmp_path / "grants.json"
    cfg.write_text(json.dumps([{
        "funder": "NSF",
        "award_id": "NSF-9",
        "title": "Phase I",
        "period_start": "2026-01-01",
        "period_end": "2027-01-01",
        "reporting_cadence": "milestone",
        "milestones": [["2026-06-30", "Prototype report"]],
    }]))
    grants = load_grants(str(cfg))
    g = grants[0]
    assert isinstance(g.period_start, date)
    assert isinstance(g.period_end, date)
    assert g.milestones == (("2026-06-30", "Prototype report"),)


def test_load_grants_defaults_empty_milestones(tmp_path):
    """Grants without milestones field should default to empty tuple."""
    cfg = tmp_path / "grants.json"
    cfg.write_text(json.dumps([{
        "funder": "X",
        "award_id": "X-1",
        "title": "t",
        "period_start": "2025-01-01",
        "period_end": "2026-01-01",
        "reporting_cadence": "final",
    }]))
    grants = load_grants(str(cfg))
    assert grants[0].milestones == ()


def test_load_grants_multiple(tmp_path):
    cfg = tmp_path / "grants.json"
    cfg.write_text(json.dumps([
        {"funder": "A", "award_id": "A-1", "title": "t1",
         "period_start": "2025-01-01", "period_end": "2027-01-01",
         "reporting_cadence": "annual"},
        {"funder": "B", "award_id": "B-2", "title": "t2",
         "period_start": "2025-06-01", "period_end": "2027-06-01",
         "reporting_cadence": "quarterly"},
    ]))
    grants = load_grants(str(cfg))
    assert len(grants) == 2
    ids = {g.award_id for g in grants}
    assert ids == {"A-1", "B-2"}


# ---------------------------------------------------------------------------
# Cadence validation (required addition — reject unknown cadence)
# ---------------------------------------------------------------------------

def test_load_grants_rejects_unknown_cadence(tmp_path):
    """A typo'd cadence must raise ValueError — not silently produce zero deadlines."""
    cfg = tmp_path / "grants.json"
    cfg.write_text(json.dumps([{
        "funder": "X",
        "award_id": "X-1",
        "title": "t",
        "period_start": "2025-01-01",
        "period_end": "2026-01-01",
        "reporting_cadence": "biennial",  # not a valid cadence
    }]))
    with pytest.raises(ValueError, match="X-1"):
        load_grants(str(cfg))


def test_load_grants_rejects_cadence_names_all_invalid(tmp_path):
    """Spot-check a few more invalid cadence strings."""
    for bad_cadence in ("monthy", "", "ANNUAL", "yearly"):
        cfg = tmp_path / f"grants_{bad_cadence}.json"
        cfg.write_text(json.dumps([{
            "funder": "X",
            "award_id": "BAD-1",
            "title": "t",
            "period_start": "2025-01-01",
            "period_end": "2026-01-01",
            "reporting_cadence": bad_cadence,
        }]))
        with pytest.raises(ValueError):
            load_grants(str(cfg))


def test_load_grants_accepts_all_valid_cadences(tmp_path):
    """All four valid cadences must load without error."""
    valid = ["annual", "quarterly", "final", "milestone"]
    for cadence in valid:
        cfg = tmp_path / f"grants_{cadence}.json"
        cfg.write_text(json.dumps([{
            "funder": "X",
            "award_id": f"X-{cadence}",
            "title": "t",
            "period_start": "2025-01-01",
            "period_end": "2026-01-01",
            "reporting_cadence": cadence,
        }]))
        grants = load_grants(str(cfg))
        assert grants[0].reporting_cadence == cadence
