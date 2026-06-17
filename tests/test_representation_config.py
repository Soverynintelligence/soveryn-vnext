from soveryn.agents.representation.config import RepresentationConfig

def test_defaults_and_env_override():
    cfg = RepresentationConfig.from_env({})
    assert cfg.enabled is True
    assert cfg.tick_interval_seconds == 900
    assert cfg.turns_per_briefing == 20
    assert cfg.dry_run is True              # SAFE default — must opt into live writes
    assert cfg.subject == "jon"
    cfg2 = RepresentationConfig.from_env({
        "SOVERYN_REPR_DRY_RUN": "false",
        "SOVERYN_REPR_TICK_SECONDS": "300",
    })
    assert cfg2.dry_run is False
    assert cfg2.tick_interval_seconds == 300
