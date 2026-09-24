"""Markdown routine docs — package defaults + data overlay."""
from __future__ import annotations

from pathlib import Path

from soveryn.automations.registry import load_automations
from soveryn.automations.routines import load_routine, routine_path, routine_summary


def test_every_catalog_automation_has_package_routine():
    catalog, order = load_automations()
    assert order
    for aid in order:
        path = routine_path(aid)
        assert path is not None, f"missing routine for {aid}"
        assert path.is_file()
        summary = routine_summary(aid)
        assert summary["has_routine"] is True
        assert summary["routine_source"] == "package"
        doc = load_routine(aid)
        assert doc is not None
        assert doc["id"] == aid
        assert "## When" in doc["markdown"]
        assert "## How" in doc["markdown"]
        assert "## Verify" in doc["markdown"]
        assert catalog[aid].title.split()[0] in doc["markdown"] or catalog[aid].title in doc["markdown"]


def test_data_overlay_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    overlay = tmp_path / "automations" / "routines"
    overlay.mkdir(parents=True)
    (overlay / "morning_brief.md").write_text(
        "# Overlay Morning Brief\n\n## When\noverride\n",
        encoding="utf-8",
    )
    doc = load_routine("morning_brief", data_root=tmp_path)
    assert doc is not None
    assert doc["source"] == "overlay"
    assert "Overlay Morning Brief" in doc["markdown"]
    assert routine_summary("morning_brief", data_root=tmp_path)["routine_source"] == "overlay"


def test_rejects_path_traversal():
    assert routine_path("../etc/passwd") is None
    assert load_routine("foo/bar") is None
