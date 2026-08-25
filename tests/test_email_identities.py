"""Citizen email identity map — house From allowlists (not personal Gmail)."""
from __future__ import annotations

import json
import os

import pytest

from soveryn.platform.email.identities import (
    allowed_from_addresses,
    board_identities,
    resolve_from_address,
)


def test_aetheria_default_and_cwg_alias():
    addrs = allowed_from_addresses("aetheria")
    assert "aetheria@soverynintelligence.com" in addrs
    assert "aetheria@carolinawatergardens.com" in addrs
    # desk send-as
    assert "pondwright@carolinawatergardens.com" in addrs
    addr, err = resolve_from_address("aetheria")
    assert err is None
    assert addr == "aetheria@soverynintelligence.com"


def test_vett_may_send_as_pondwright():
    addr, err = resolve_from_address(
        "vett", "pondwright@carolinawatergardens.com"
    )
    assert err is None
    assert addr == "pondwright@carolinawatergardens.com"


def test_rejects_foreign_from():
    addr, err = resolve_from_address("eve", "jon@gmail.com")
    assert addr is None
    assert err and "not allowed" in err


def test_env_overlay(monkeypatch):
    monkeypatch.setenv(
        "SOVERYN_EMAIL_IDENTITIES",
        json.dumps(
            {
                "eve": {
                    "default": "eve@example.test",
                    "aliases": ["eve@example.test", "presence@example.test"],
                }
            }
        ),
    )
    addrs = allowed_from_addresses("eve")
    assert "eve@example.test" in addrs
    assert "presence@example.test" in addrs
    addr, err = resolve_from_address("eve")
    assert err is None and addr == "eve@example.test"


def test_board_identities_shape():
    board = board_identities()
    assert "soverynintelligence.com" in board["domains"]
    assert "carolinawatergardens.com" in board["domains"]
    assert board["by_citizen"]["aetheria"]["default"].startswith("aetheria@")
    assert board["desk"]["pondwright"]["default"].endswith(
        "@carolinawatergardens.com"
    )
    assert board.get("production") is False
    assert board.get("status") == "not_production"
    assert "NOT PRODUCTION" in (board.get("reading") or "")


def test_connectors_board_includes_email_identities():
    from soveryn.citizens.connectors import board_payload, for_citizen

    payload = board_payload()
    assert "email_identities" in payload
    assert payload["house"].get("email_not_production") is True
    assert "NOT PRODUCTION" in (payload.get("reading") or "")
    aetheria_email = [
        c for c in for_citizen("aetheria") if c.id == "email"
    ][0]
    assert aetheria_email.email_from == "aetheria@soverynintelligence.com"
    assert "pondwright@carolinawatergardens.com" in aetheria_email.email_aliases
    assert aetheria_email.armed is False
