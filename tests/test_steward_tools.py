"""Tests for steward agent tools — grant_deadlines, grant_status, list_grants, grant_submit.

Covers:
- Tools registered for aetheria AND vett, NOT scotty.
- Read-tool flow over seeded temp grants.json returns computed deadlines.
- grant_submit records a submission then that report no longer appears in grant_deadlines (done-overlay end-to-end).
- Read tool over MISSING config returns empty (graceful).
- grant_submit with a bad date → ToolArgError.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from soveryn.platform.tools.registry import ToolArgError, ToolRegistry


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _seed_grants(path: Path) -> None:
    path.write_text(
        json.dumps([
            {
                "funder": "Cosmos Institute",
                "award_id": "COSMOS-1",
                "title": "Sovereign AI",
                "period_start": "2025-09-01",
                "period_end": "2027-08-31",
                "reporting_cadence": "annual",
            }
        ]),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# registration tests
# ---------------------------------------------------------------------------

def test_steward_tools_registered_for_aetheria_and_vett(tmp_path: Path) -> None:
    from soveryn.platform.steward.tools import register_steward_tools

    registry = ToolRegistry(audit_hook=None)
    grants_path = tmp_path / "grants.json"
    subs_path = tmp_path / "subs.json"
    _seed_grants(grants_path)

    register_steward_tools(
        registry,
        grants_config_path=str(grants_path),
        submissions_path=str(subs_path),
    )

    steward_tool_names = {"grant_deadlines", "grant_status", "list_grants", "grant_submit"}

    aetheria_names = {s.name for s in registry.iter_tools_for_agent("aetheria")}
    vett_names = {s.name for s in registry.iter_tools_for_agent("vett")}
    scotty_names = {s.name for s in registry.iter_tools_for_agent("scotty")}

    assert steward_tool_names <= aetheria_names, \
        f"aetheria missing steward tools: {steward_tool_names - aetheria_names}"
    assert steward_tool_names <= vett_names, \
        f"vett missing steward tools: {steward_tool_names - vett_names}"
    assert steward_tool_names.isdisjoint(scotty_names), \
        f"scotty should NOT see steward tools: {steward_tool_names & scotty_names}"


# ---------------------------------------------------------------------------
# grant_deadlines — computed output from engine
# ---------------------------------------------------------------------------

def test_grant_deadlines_returns_computed_obligations(tmp_path: Path) -> None:
    from soveryn.platform.steward.tools import register_steward_tools

    registry = ToolRegistry(audit_hook=None)
    grants_path = tmp_path / "grants.json"
    subs_path = tmp_path / "subs.json"
    _seed_grants(grants_path)

    register_steward_tools(
        registry,
        grants_config_path=str(grants_path),
        submissions_path=str(subs_path),
    )

    result = registry.invoke("aetheria", "grant_deadlines", {"window_days": 500})

    assert isinstance(result, list)
    assert len(result) >= 1
    cosmos = [r for r in result if r["award_id"] == "COSMOS-1"]
    assert cosmos, "COSMOS-1 should appear in deadlines within 500-day window"
    for item in cosmos:
        assert "due_date" in item
        assert "status" in item
        assert item["status"] in ("upcoming", "overdue"), \
            f"status must be upcoming or overdue (not done), got {item['status']!r}"
        # due_date must be an ISO string (JSON-serializable), not a date object
        assert isinstance(item["due_date"], str), "due_date must be ISO string"


def test_grant_deadlines_excludes_done_obligations(tmp_path: Path) -> None:
    """grant_submit → marks an obligation done → grant_deadlines no longer returns it."""
    from soveryn.platform.steward.tools import register_steward_tools

    registry = ToolRegistry(audit_hook=None)
    grants_path = tmp_path / "grants.json"
    subs_path = tmp_path / "subs.json"
    _seed_grants(grants_path)

    register_steward_tools(
        registry,
        grants_config_path=str(grants_path),
        submissions_path=str(subs_path),
    )

    # Get deadlines before submission
    before = registry.invoke("aetheria", "grant_deadlines", {"window_days": 500})
    cosmos_before = [r for r in before if r["award_id"] == "COSMOS-1"]
    assert cosmos_before, "need at least one COSMOS-1 deadline to test the overlay"

    # Submit the first deadline
    first_due = cosmos_before[0]["due_date"]
    submit_result = registry.invoke(
        "aetheria",
        "grant_submit",
        {"award_id": "COSMOS-1", "report_date": first_due},
    )
    assert submit_result["ok"] is True
    assert submit_result["award_id"] == "COSMOS-1"
    assert submit_result["report_date"] == first_due

    # Deadlines after submission must not include the submitted due_date
    after = registry.invoke("aetheria", "grant_deadlines", {"window_days": 500})
    still_present = [r for r in after if r["due_date"] == first_due]
    assert not still_present, \
        f"submitted deadline {first_due!r} still appears in grant_deadlines after submission"


# ---------------------------------------------------------------------------
# graceful missing config
# ---------------------------------------------------------------------------

def test_grant_deadlines_returns_empty_when_config_missing(tmp_path: Path) -> None:
    from soveryn.platform.steward.tools import register_steward_tools

    registry = ToolRegistry(audit_hook=None)
    grants_path = tmp_path / "nonexistent_grants.json"   # does NOT exist
    subs_path = tmp_path / "subs.json"

    register_steward_tools(
        registry,
        grants_config_path=str(grants_path),
        submissions_path=str(subs_path),
    )

    result = registry.invoke("aetheria", "grant_deadlines", {})
    assert result == [], f"expected empty list for missing config, got {result!r}"


def test_list_grants_returns_empty_when_config_missing(tmp_path: Path) -> None:
    from soveryn.platform.steward.tools import register_steward_tools

    registry = ToolRegistry(audit_hook=None)
    grants_path = tmp_path / "nonexistent_grants.json"
    subs_path = tmp_path / "subs.json"

    register_steward_tools(
        registry,
        grants_config_path=str(grants_path),
        submissions_path=str(subs_path),
    )

    result = registry.invoke("aetheria", "list_grants", {})
    assert result == [], f"expected empty list for missing config, got {result!r}"


def test_grant_status_returns_empty_when_config_missing(tmp_path: Path) -> None:
    from soveryn.platform.steward.tools import register_steward_tools

    registry = ToolRegistry(audit_hook=None)
    grants_path = tmp_path / "nonexistent_grants.json"
    subs_path = tmp_path / "subs.json"

    register_steward_tools(
        registry,
        grants_config_path=str(grants_path),
        submissions_path=str(subs_path),
    )

    result = registry.invoke("aetheria", "grant_status", {"award_id": "COSMOS-1"})
    assert result["obligations"] == []


# ---------------------------------------------------------------------------
# list_grants
# ---------------------------------------------------------------------------

def test_list_grants_returns_grant_metadata(tmp_path: Path) -> None:
    from soveryn.platform.steward.tools import register_steward_tools

    registry = ToolRegistry(audit_hook=None)
    grants_path = tmp_path / "grants.json"
    subs_path = tmp_path / "subs.json"
    _seed_grants(grants_path)

    register_steward_tools(
        registry,
        grants_config_path=str(grants_path),
        submissions_path=str(subs_path),
    )

    result = registry.invoke("vett", "list_grants", {})

    assert isinstance(result, list)
    assert len(result) == 1
    entry = result[0]
    assert entry["award_id"] == "COSMOS-1"
    assert entry["funder"] == "Cosmos Institute"
    assert entry["title"] == "Sovereign AI"
    assert isinstance(entry["period_start"], str)
    assert isinstance(entry["period_end"], str)
    assert entry["cadence"] == "annual"


# ---------------------------------------------------------------------------
# grant_status
# ---------------------------------------------------------------------------

def test_grant_status_returns_obligations_for_award(tmp_path: Path) -> None:
    from soveryn.platform.steward.tools import register_steward_tools

    registry = ToolRegistry(audit_hook=None)
    grants_path = tmp_path / "grants.json"
    subs_path = tmp_path / "subs.json"
    _seed_grants(grants_path)

    register_steward_tools(
        registry,
        grants_config_path=str(grants_path),
        submissions_path=str(subs_path),
    )

    result = registry.invoke("vett", "grant_status", {"award_id": "COSMOS-1"})
    assert "award_id" in result
    assert result["award_id"] == "COSMOS-1"
    assert isinstance(result["obligations"], list)
    assert len(result["obligations"]) >= 1


def test_grant_status_bad_award_id_raises(tmp_path: Path) -> None:
    from soveryn.platform.steward.tools import register_steward_tools

    registry = ToolRegistry(audit_hook=None)
    grants_path = tmp_path / "grants.json"
    subs_path = tmp_path / "subs.json"
    _seed_grants(grants_path)

    register_steward_tools(
        registry,
        grants_config_path=str(grants_path),
        submissions_path=str(subs_path),
    )

    with pytest.raises(ToolArgError, match="award_id"):
        registry.invoke("aetheria", "grant_status", {"award_id": ""})


# ---------------------------------------------------------------------------
# grant_submit — validation
# ---------------------------------------------------------------------------

def test_grant_submit_bad_date_raises_tool_arg_error(tmp_path: Path) -> None:
    from soveryn.platform.steward.tools import register_steward_tools

    registry = ToolRegistry(audit_hook=None)
    grants_path = tmp_path / "grants.json"
    subs_path = tmp_path / "subs.json"
    _seed_grants(grants_path)

    register_steward_tools(
        registry,
        grants_config_path=str(grants_path),
        submissions_path=str(subs_path),
    )

    with pytest.raises(ToolArgError, match="report_date"):
        registry.invoke(
            "aetheria",
            "grant_submit",
            {"award_id": "COSMOS-1", "report_date": "not-a-date"},
        )


def test_grant_submit_empty_award_id_raises(tmp_path: Path) -> None:
    from soveryn.platform.steward.tools import register_steward_tools

    registry = ToolRegistry(audit_hook=None)
    grants_path = tmp_path / "grants.json"
    subs_path = tmp_path / "subs.json"
    _seed_grants(grants_path)

    register_steward_tools(
        registry,
        grants_config_path=str(grants_path),
        submissions_path=str(subs_path),
    )

    with pytest.raises(ToolArgError, match="award_id"):
        registry.invoke(
            "aetheria",
            "grant_submit",
            {"award_id": "", "report_date": "2026-09-01"},
        )


def test_grant_submit_returns_structured_result(tmp_path: Path) -> None:
    from soveryn.platform.steward.tools import register_steward_tools

    registry = ToolRegistry(audit_hook=None)
    grants_path = tmp_path / "grants.json"
    subs_path = tmp_path / "subs.json"
    _seed_grants(grants_path)

    register_steward_tools(
        registry,
        grants_config_path=str(grants_path),
        submissions_path=str(subs_path),
    )

    result = registry.invoke(
        "aetheria",
        "grant_submit",
        {"award_id": "COSMOS-1", "report_date": "2026-09-01", "note": "Q1 submitted"},
    )

    assert result["ok"] is True
    assert result["award_id"] == "COSMOS-1"
    assert result["report_date"] == "2026-09-01"
    assert isinstance(result["submitted_at"], str)   # ISO string, not date object


# ---------------------------------------------------------------------------
# vett can also invoke read tools (same data, different owner)
# ---------------------------------------------------------------------------

def test_vett_can_invoke_grant_deadlines(tmp_path: Path) -> None:
    from soveryn.platform.steward.tools import register_steward_tools

    registry = ToolRegistry(audit_hook=None)
    grants_path = tmp_path / "grants.json"
    subs_path = tmp_path / "subs.json"
    _seed_grants(grants_path)

    register_steward_tools(
        registry,
        grants_config_path=str(grants_path),
        submissions_path=str(subs_path),
    )

    result = registry.invoke("vett", "grant_deadlines", {"window_days": 500})
    assert isinstance(result, list)


def test_vett_can_invoke_grant_submit(tmp_path: Path) -> None:
    from soveryn.platform.steward.tools import register_steward_tools

    registry = ToolRegistry(audit_hook=None)
    grants_path = tmp_path / "grants.json"
    subs_path = tmp_path / "subs.json"
    _seed_grants(grants_path)

    register_steward_tools(
        registry,
        grants_config_path=str(grants_path),
        submissions_path=str(subs_path),
    )

    result = registry.invoke(
        "vett",
        "grant_submit",
        {"award_id": "COSMOS-1", "report_date": "2026-09-01"},
    )
    assert result["ok"] is True
