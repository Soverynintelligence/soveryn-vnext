"""Citizen connectors catalog and email tool registration."""
from __future__ import annotations

import os

from soveryn.citizens.connectors import (
    AUTOMATION_AUTO_APPROVE_TOOLS,
    FOUNDING_GRANTS,
    board_payload,
    email_armed,
    for_citizen,
    requires_approval,
)
from soveryn.platform.email.tools import register_email_tools
from soveryn.platform.tools.registry import ToolRegistry


def test_founding_grants_give_web_to_aetheria_and_vett_not_scotty():
    assert "web" in FOUNDING_GRANTS["aetheria"]
    assert "web" in FOUNDING_GRANTS["vett"]
    assert "web" not in FOUNDING_GRANTS["scotty"]
    assert "code" in FOUNDING_GRANTS["scotty"]


def test_for_citizen_marks_email_unarmed_without_smtp(monkeypatch):
    monkeypatch.delenv("SOVERYN_SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SOVERYN_SMTP_FROM", raising=False)
    monkeypatch.delenv("SMTP_FROM", raising=False)
    rows = {c.id: c for c in for_citizen("aetheria")}
    assert rows["email"].granted is True
    assert rows["email"].armed is False
    assert rows["web"].granted is True


def test_email_armed_when_host_and_from_set(monkeypatch):
    monkeypatch.setenv("SOVERYN_SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("SOVERYN_SMTP_FROM", "house@example.test")
    ok, why = email_armed()
    assert ok is True
    assert "SMTP" in why


def test_register_email_tools_only_when_armed(monkeypatch):
    monkeypatch.delenv("SOVERYN_SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SOVERYN_SMTP_FROM", raising=False)
    reg = ToolRegistry(active_agents=("aetheria", "vett", "scotty"))
    n = register_email_tools(reg, owner_agent="aetheria")
    assert n == 0

    monkeypatch.setenv("SOVERYN_SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("SOVERYN_SMTP_FROM", "house@example.test")
    reg2 = ToolRegistry(active_agents=("aetheria", "vett", "scotty"))
    n2 = register_email_tools(reg2, owner_agent="aetheria")
    assert n2 >= 1
    # tool is registered for aetheria
    names = [k[1] for k in reg2._tools if k[0] == "aetheria"]
    assert "email_send" in names


def test_board_payload_shape():
    p = board_payload()
    assert "catalog" in p and "by_citizen" in p and "house" in p
    assert "aetheria" in p["by_citizen"]
    assert any(c["id"] == "web" for c in p["by_citizen"]["aetheria"])


def test_requires_approval_web_ungated_writes_gated():
    # House SearXNG reads — never Gate (Jon: research must not hang).
    assert requires_approval("web_search") is False
    assert requires_approval("fetch_url") is False
    assert requires_approval("web_search", source="direct") is False
    assert requires_approval("web_search", source="commission") is False
    # Write egress still needs a yes.
    assert requires_approval("x_post") is True
    assert requires_approval("email_send") is True
    assert requires_approval("messenger_send") is True
    assert requires_approval("signal_send") is False  # Direct Line, ungated
    assert requires_approval("read_file") is False  # house-local


def test_automation_source_auto_approves_read_tools_not_writes():
    """Scheduler / Run now must not hang on web_search — reads pass, writes stay gated."""
    for tool in AUTOMATION_AUTO_APPROVE_TOOLS:
        assert requires_approval(tool, source="automation") is False
    # web reads ungated for any source; x_feed still gated outside automation
    assert requires_approval("web_search", source="direct") is False
    assert requires_approval("x_feed", source="direct") is True
    assert requires_approval("email_list", source="direct") is False
    assert requires_approval("x_post", source="automation") is True
    assert requires_approval("email_send", source="automation") is True
    assert requires_approval("messenger_send", source="automation") is True
