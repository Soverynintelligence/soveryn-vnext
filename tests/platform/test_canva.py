"""Canva Connect unit tests (no live network)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from soveryn.platform.canva.config import load_config, load_brand_templates
from soveryn.platform.canva.oauth import make_pkce, make_state, _save_tokens, load_tokens
from soveryn.platform.canva.tools import register_canva_tools
from soveryn.platform.tools.registry import ToolRegistry


def test_pkce_shapes():
    verifier, challenge = make_pkce()
    assert 43 <= len(verifier) <= 128
    assert len(challenge) >= 43
    assert make_state()


def test_load_brand_templates(monkeypatch):
    monkeypatch.setenv(
        "SOVERYN_CANVA_TEMPLATES", "hl:AAA,soveryn:BBB, cwg:CCC"
    )
    m = load_brand_templates()
    assert m == {"hl": "AAA", "soveryn": "BBB", "cwg": "CCC"}


def test_config_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("SOVERYN_CANVA_CLIENT_ID", "cid")
    monkeypatch.setenv("SOVERYN_CANVA_CLIENT_SECRET", "sec")
    cfg = load_config()
    assert cfg.configured
    assert cfg.token_path == tmp_path / "canva" / "tokens.json"
    assert cfg.media_dir == tmp_path / "media" / "canva"
    assert not cfg.authorized


def test_clean_quoted_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("SOVERYN_CANVA_CLIENT_ID", '"OC-abc123"')
    monkeypatch.setenv("SOVERYN_CANVA_CLIENT_SECRET", "'sekrit'")
    cfg = load_config()
    assert cfg.client_id == "OC-abc123"
    assert cfg.client_secret == "sekrit"


def test_token_roundtrip(tmp_path):
    path = tmp_path / "tokens.json"
    _save_tokens(
        path,
        {
            "access_token": "a",
            "refresh_token": "r",
            "expires_in": 3600,
            "token_type": "Bearer",
        },
    )
    t = load_tokens(path)
    assert t is not None
    assert t["access_token"] == "a"
    assert t["refresh_token"] == "r"
    assert t["expires_at"] > 0


def test_register_canva_tools():
    reg = ToolRegistry()
    register_canva_tools(reg, owner_agent="eve")
    names = {t.name for t in reg.iter_tools_for_agent("eve")}
    assert "canva_status" in names
    assert "canva_autofill_post" in names
    assert "canva_export_design" in names


def test_canva_status_tool(tmp_path, monkeypatch):
    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("SOVERYN_CANVA_CLIENT_ID", raising=False)
    monkeypatch.delenv("SOVERYN_CANVA_CLIENT_SECRET", raising=False)
    reg = ToolRegistry()
    register_canva_tools(reg, owner_agent="eve")
    tool = next(
        t for t in reg.iter_tools_for_agent("eve") if t.name == "canva_status"
    )
    out = tool.handler({})
    assert out["ok"] is True
    assert out["configured"] is False
