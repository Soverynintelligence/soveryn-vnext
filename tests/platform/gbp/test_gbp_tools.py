"""CWG Google Business tools — Gate surface, no ads."""
from __future__ import annotations

import pytest

from soveryn.platform.gbp.client import create_local_post
from soveryn.platform.gbp.config import GbpConfig
from soveryn.platform.gbp.tools import build_eve_gbp_post_tool
from soveryn.platform.tools.registry import ToolArgError
from soveryn.citizens.connectors import requires_approval


def _cfg(tmp_path):
    return GbpConfig(
        client_id="id",
        client_secret="test-gbp-client",  # ggignore
        redirect_uri="http://127.0.0.1:8766/oauth/gbp/callback",
        token_path=tmp_path / "tokens.json",
        location_path=tmp_path / "location.json",
        location="accounts/1/locations/2",
        cta_url="https://carolinawatergardens.com",
    )


def test_gbp_post_is_always_gated():
    assert requires_approval("eve_gbp_post") is True
    assert requires_approval("eve_gbp_post", source="automation") is True
    assert requires_approval("eve_gbp_status") is False


def test_tool_rejects_non_cwg():
    spec = build_eve_gbp_post_tool(post_fn=lambda **_k: {"ok": True})
    with pytest.raises(ToolArgError):
        spec.handler({"brand": "soveryn", "caption": "House post."})


def test_unconfigured_is_honest(tmp_path):
    cfg = _cfg(tmp_path)
    cfg = GbpConfig(
        client_id="",
        client_secret="",
        redirect_uri=cfg.redirect_uri,
        token_path=cfg.token_path,
        location_path=cfg.location_path,
        location="",
        cta_url=cfg.cta_url,
    )
    out = create_local_post(summary="Spring water.", cfg=cfg, token="x")
    assert out["ok"] is False
    assert out["status"] == "needs_oauth_client"


def test_create_post_calls_http(tmp_path):
    cfg = _cfg(tmp_path)
    seen: list = []

    def http(url, *, method="GET", token="", body=None):
        seen.append((method, url, body))
        return {"name": "accounts/1/locations/2/localPosts/9"}

    out = create_local_post(
        summary="The water is waiting.",
        cfg=cfg,
        token="tok",
        http=http,
    )
    assert out["ok"] is True
    assert out["status"] == "posted"
    assert seen[0][0] == "POST"
    assert "localPosts" in seen[0][1]


def test_tool_posts_cwg():
    spec = build_eve_gbp_post_tool(
        post_fn=lambda summary, image_path=None: {
            "ok": True,
            "status": "posted",
            "summary": summary,
        }
    )
    out = spec.handler({"brand": "cwg", "caption": "Dragonflies at dusk."})
    assert out["ok"] is True
    assert out["status"] == "posted"
