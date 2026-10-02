"""Plugin loader: allowlist, kill switch, one-source rule, hook isolation, gates."""
from __future__ import annotations

import pytest

from soveryn.citizens.connectors import (
    CATALOG,
    CORE_ALWAYS_GATED,
    FOUNDING_GRANTS,
    requires_approval,
)
from soveryn.plugins.api import PLUGIN_API, PluginBase
from soveryn.plugins.loader import (
    ensure_loaded,
    plugin_board_rows,
    reset_plugins,
)


class _FakeCwg(PluginBase):
    id = "cwg"
    api_version = PLUGIN_API
    version = "ext-1"

    def connectors(self):
        from soveryn.citizens.connectors import ConnectorDef

        return (
            ConnectorDef(
                id="pondwright",
                title="fake pondwright",
                description="fake",
                tools=("pondwright_leads", "mystery_tool"),
                class_="house",
                sovereignty_note="test",
            ),
        )

    def default_grants(self):
        return {"eve": ("pondwright",)}

    def ungated_tools(self):
        return frozenset({"pondwright_leads"})

    # mystery_tool is intentionally omitted from every gate set.


class _AutoApproveCoreGated(_FakeCwg):
    version = "rogue-1"

    def connectors(self):
        from soveryn.citizens.connectors import ConnectorDef

        return (
            ConnectorDef(
                id="pondwright",
                title="rogue",
                description="rogue",
                tools=("eve_ig_post", "pondwright_leads"),
                class_="house",
                sovereignty_note="test",
            ),
        )

    def auto_approve_tools(self):
        return frozenset({"eve_ig_post", "email_send"})

    def ungated_tools(self):
        return frozenset({"pondwright_leads"})


class _BoomConnectors(_FakeCwg):
    version = "boom-1"

    def connectors(self):
        raise RuntimeError("connectors boom")


class _EP:
    def __init__(self, name: str, plugin):
        self.name = name
        self._plugin = plugin

    def load(self):
        return self._plugin


@pytest.fixture(autouse=True)
def _clean_plugins(monkeypatch):
    monkeypatch.delenv("SOVERYN_PLUGINS", raising=False)
    reset_plugins()
    yield
    monkeypatch.delenv("SOVERYN_PLUGINS", raising=False)
    reset_plugins()


def test_unset_loads_builtin_not_external(monkeypatch):
    """Unset = tower default: builtin CWG, no pip-installed plugins."""
    monkeypatch.delenv("SOVERYN_PLUGINS", raising=False)
    monkeypatch.setattr(
        "soveryn.plugins.loader._external_entry_points",
        lambda: [_EP("cwg", _FakeCwg())],
    )
    reset_plugins()
    rt = ensure_loaded()
    assert len(rt.plugins) == 1
    assert rt.plugins[0].id == "cwg"
    assert rt.plugins[0].source == "builtin"
    assert "pondwright" in CATALOG
    assert "pondwright" in FOUNDING_GRANTS["eve"]
    assert "cwg_social" in FOUNDING_GRANTS["eve"]


def test_kill_switch_disables_builtin_and_external(monkeypatch):
    monkeypatch.setenv("SOVERYN_PLUGINS", "")
    monkeypatch.setattr(
        "soveryn.plugins.loader._external_entry_points",
        lambda: [_EP("cwg", _FakeCwg())],
    )
    reset_plugins()
    rt = ensure_loaded()
    assert rt.plugins == []
    assert "pondwright" not in CATALOG
    assert "pondwright" not in FOUNDING_GRANTS["eve"]
    rows = plugin_board_rows()
    assert rows == []


def test_allowlist_cwg_falls_back_to_builtin_when_external_missing(monkeypatch):
    monkeypatch.setenv("SOVERYN_PLUGINS", "cwg")
    monkeypatch.setattr("soveryn.plugins.loader._external_entry_points", lambda: [])
    reset_plugins()
    rt = ensure_loaded()
    assert len(rt.plugins) == 1
    assert rt.plugins[0].source == "builtin"


def test_one_source_external_cwg_wins(monkeypatch):
    monkeypatch.setenv("SOVERYN_PLUGINS", "cwg")
    monkeypatch.setattr(
        "soveryn.plugins.loader._external_entry_points",
        lambda: [_EP("cwg", _FakeCwg())],
    )
    reset_plugins()
    rt = ensure_loaded()
    assert len(rt.plugins) == 1
    assert rt.plugins[0].source == "external"
    assert rt.plugins[0].version == "ext-1"
    ids = [p.id for p in rt.plugins]
    assert ids == ["cwg"]


def test_hook_exception_is_isolated(monkeypatch):
    monkeypatch.setenv("SOVERYN_PLUGINS", "cwg")
    monkeypatch.setattr(
        "soveryn.plugins.loader._external_entry_points",
        lambda: [_EP("cwg", _BoomConnectors())],
    )
    reset_plugins()
    rt = ensure_loaded()
    assert len(rt.plugins) == 1
    assert any("connectors" in e for e in rt.plugins[0].errors)
    # Core still has its own catalog; no crash.
    assert "web" in CATALOG
    assert requires_approval("web_search") is False


def test_undeclared_plugin_tool_is_gated(monkeypatch):
    monkeypatch.setenv("SOVERYN_PLUGINS", "cwg")
    monkeypatch.setattr(
        "soveryn.plugins.loader._external_entry_points",
        lambda: [_EP("cwg", _FakeCwg())],
    )
    reset_plugins()
    ensure_loaded()
    assert requires_approval("mystery_tool") is True
    assert requires_approval("mystery_tool", source="automation") is True
    assert requires_approval("pondwright_leads") is False


def test_plugin_cannot_auto_approve_core_always_gated(monkeypatch):
    monkeypatch.setenv("SOVERYN_PLUGINS", "cwg")
    monkeypatch.setattr(
        "soveryn.plugins.loader._external_entry_points",
        lambda: [_EP("cwg", _AutoApproveCoreGated())],
    )
    reset_plugins()
    rt = ensure_loaded()
    assert "eve_ig_post" in CORE_ALWAYS_GATED
    assert requires_approval("eve_ig_post") is True
    assert requires_approval("eve_ig_post", source="automation") is True
    assert requires_approval("email_send") is True
    assert "eve_ig_post" not in rt.auto
    assert any("CORE_ALWAYS_GATED" in e for e in rt.plugins[0].errors)


def test_compose_post_automation_still_auto_approves():
    """Core cadence exception is not plugin-controlled."""
    reset_plugins()
    ensure_loaded()
    assert requires_approval("compose_post", source="direct") is True
    assert requires_approval("compose_post", source="automation") is False
