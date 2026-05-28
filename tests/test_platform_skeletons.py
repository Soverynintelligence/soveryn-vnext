"""Tests for supervisor, telemetry, and repair skeletons."""

from pathlib import Path

import pytest

from soveryn.platform.repair import RepairRecipeError, load_recipe
from soveryn.platform.supervisor import HealthCheck, HealthProbe
from soveryn.platform.telemetry import TelemetryEvent


def test_supervisor_health_probe_shape_is_declared():
    check = HealthCheck("aetheria-chat", "systemd:aetheria-chat.service", timeout_seconds=5.0)

    assert check.name == "aetheria-chat"
    assert check.target == "systemd:aetheria-chat.service"
    result = HealthProbe().check(check)
    assert result.name == "aetheria-chat"
    assert result.state == "unknown"


def test_telemetry_event_shape_is_reviewable():
    event = TelemetryEvent(
        source="platform.repair",
        event_type="recipe.loaded",
        level="info",
        payload={"recipe": "restart"},
    )

    assert event.source == "platform.repair"
    assert event.payload == {"recipe": "restart"}
    assert event.created_at


def test_sample_repair_recipe_parses():
    path = Path("soveryn/platform/repair/recipes/repair_restart_aetheria_chat_surface.yaml")
    recipe = load_recipe(path)

    assert recipe.name == "repair_restart_aetheria_chat_surface"
    assert recipe.tier == "A"
    assert recipe.preconditions == (
        "aetheria.chat_surface.http_health != 200",
        "aetheria.chat_surface.last_response_ms > 60000",
    )
    assert recipe.actions == ("systemctl --user restart aetheria-chat.service",)
    assert recipe.verify == ("aetheria.chat_surface.http_health == 200",)
    assert recipe.rollback == ()
    assert recipe.on_repeated_failure == "escalate"


def test_invalid_repair_recipe_tier_rejected(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "name: bad\n"
        "tier: Z\n"
        "preconditions:\n"
        "  - x\n"
        "action:\n"
        "  - y\n"
        "verify:\n"
        "  - z\n"
    )

    with pytest.raises(RepairRecipeError, match="tier"):
        load_recipe(bad)
