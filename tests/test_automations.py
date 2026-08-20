"""Tests for SOVERYN Automations v0 (dry-run layer)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from soveryn.automations import load_automations
from soveryn.automations.deliver import deliver
from soveryn.automations.runner import main as runner_main, run_automation

ROOT = Path(__file__).resolve().parent.parent

REQUIRED_IDS = [
    "morning_brief",
    "ai_news_digest",
    "x_trends_digest",
    "competitor_watch",
    "daily_planner",
    "weekly_review",
    "task_extractor",
    "paper_watch",
    "weekend_deep_dive",
]


def test_catalog_count_at_least_nine():
    catalog, order = load_automations()
    assert len(order) >= 9
    assert len(catalog) == len(order)


def test_required_ids_present():
    _, order = load_automations()
    for automation_id in REQUIRED_IDS:
        assert automation_id in order, f"missing required automation: {automation_id}"


def test_catalog_ids_unique():
    _, order = load_automations()
    assert len(order) == len(set(order))


def test_spec_fields_populated():
    catalog, _ = load_automations()
    for spec in catalog.values():
        assert spec.id
        assert spec.title
        assert spec.category in {"news", "productivity", "research"}
        assert spec.agent in {"aetheria", "vett"}
        assert spec.cron
        assert spec.prompt.strip()
        assert spec.delivery.channel
        assert spec.delivery.target
        assert spec.dry_run is True


def test_dry_run_returns_ok_and_would_run(tmp_path, monkeypatch):
    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    result = run_automation("morning_brief", dry_run=True)
    assert result["id"] == "morning_brief"
    assert result["agent"] == "aetheria"
    assert result["status"] == "ok"
    assert result["dry_run"] is True
    # preview of prompt/delivery present — default channel is Command Center
    assert "prompt" in result and result["prompt"]
    assert result["channels"] == ["command_center"]
    assert result["delivery"]["channel"] == "command_center"
    assert result["delivery"]["channels"] == ["command_center"]
    assert result["delivery"]["target"] == "jon"
    assert result["delivery"]["preview"]


def test_run_automation_unknown_id_raises():
    with pytest.raises(KeyError):
        run_automation("does_not_exist")


def test_deliver_refuses_live():
    catalog, _ = load_automations()
    spec = catalog["morning_brief"]
    out = deliver(spec, dry_run=False)
    assert out["status"] == "refused"
    assert out["dry_run"] is False


def test_channel_prefs_default_and_override(tmp_path, monkeypatch):
    from soveryn.automations.prefs import resolve_channels, set_channels

    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    assert resolve_channels("morning_brief") == ["command_center"]
    saved = set_channels("morning_brief", ["command_center", "signal"])
    assert saved == ["command_center", "signal"]
    assert resolve_channels("morning_brief") == ["command_center", "signal"]
    result = run_automation("morning_brief", dry_run=True)
    assert result["channels"] == ["command_center", "signal"]
    assert "command_center" in result["delivery"]["preview"]
    assert "signal" in result["delivery"]["preview"]


def test_set_channels_rejects_empty(tmp_path, monkeypatch):
    from soveryn.automations.prefs import set_channels

    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    with pytest.raises(ValueError):
        set_channels("morning_brief", [])


def test_runner_cli_live_refused(capsys):
    rc = runner_main(["morning_brief", "--live"])
    captured = capsys.readouterr()
    assert rc == 3
    assert "refused" in captured.err
    assert "in-process" in captured.err


def test_runner_cli_list(capsys):
    rc = runner_main(["--list"])
    captured = capsys.readouterr()
    assert rc == 0
    for automation_id in REQUIRED_IDS:
        assert automation_id in captured.out


def test_runner_cli_run_dry_run(capsys):
    rc = runner_main(["morning_brief"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "status     : ok" in captured.out
    assert "dry_run    : True" in captured.out


def test_runner_cli_unknown_id(capsys):
    rc = runner_main(["nope"])
    captured = capsys.readouterr()
    assert rc == 4
    assert "unknown automation" in captured.err


def test_cli_module_live_refused():
    proc = subprocess.run(
        [sys.executable, "-m", "soveryn.automations.runner", "morning_brief", "--live"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 3
    assert "refused" in proc.stderr


def test_cli_module_list():
    proc = subprocess.run(
        [sys.executable, "-m", "soveryn.automations.runner", "--list"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert "morning_brief" in proc.stdout


def test_cli_module_run():
    proc = subprocess.run(
        [sys.executable, "-m", "soveryn.automations.runner", "morning_brief"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert "status     : ok" in proc.stdout
    assert "dry_run    : True" in proc.stdout
