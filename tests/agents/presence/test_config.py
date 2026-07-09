from soveryn.agents.presence.config import PresenceConfig


def test_default_config_has_niche_and_own_handle():
    cfg = PresenceConfig.default()
    assert cfg.own_handle == "Soveryn_AI"
    assert any("sovereign" in t.lower() for t in cfg.niche_terms)
    assert cfg.score_threshold > 0
    assert cfg.max_drafts_per_scan >= 1
