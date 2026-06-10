from pathlib import Path


def test_heartbeat_daemon_defaults_under_data_root():
    from soveryn.agents.heartbeat import daemon
    assert daemon.DEFAULT_LATTICE_DB == Path.home() / "soveryn_vnext" / "data" / "memory" / "lattice_vnext.db"
    assert daemon.DEFAULT_CONV_DB == Path.home() / "soveryn_vnext" / "data" / "memory" / "conversations_vnext.db"
    assert daemon.DEFAULT_SALIENCE_DB == Path.home() / "soveryn_vnext" / "data" / "memory" / "salience_vnext.db"


def test_dream_daemon_defaults_under_data_root():
    from soveryn.agents.dream import daemon
    assert daemon.DEFAULT_LATTICE_DB == Path.home() / "soveryn_vnext" / "data" / "memory" / "lattice_vnext.db"
    assert daemon.DEFAULT_CONV_DB == Path.home() / "soveryn_vnext" / "data" / "memory" / "conversations_vnext.db"


def test_vett_patrol_daemon_defaults_under_data_root():
    from soveryn.agents.vett.patrol import daemon
    assert daemon.DEFAULT_LATTICE_DB == Path.home() / "soveryn_vnext" / "data" / "memory" / "lattice_vnext.db"
    assert daemon.DEFAULT_CONV_DB == Path.home() / "soveryn_vnext" / "data" / "memory" / "conversations_vnext.db"


def test_signal_bridge_daemon_defaults_under_data_root():
    from soveryn.agents.signal_bridge import daemon
    assert daemon.DEFAULT_LATTICE_DB == Path.home() / "soveryn_vnext" / "data" / "memory" / "lattice_vnext.db"


def test_no_soveryn_complete_in_daemon_defaults():
    """Defense in depth: no daemon module default should mention soveryn_complete."""
    from soveryn.agents.heartbeat import daemon as hb
    from soveryn.agents.dream import daemon as dr
    from soveryn.agents.vett.patrol import daemon as vp
    from soveryn.agents.signal_bridge import daemon as sb
    for mod in (hb, dr, vp, sb):
        for name in dir(mod):
            if name.startswith("DEFAULT_") and name.endswith(("_DB", "_DIR")):
                value = getattr(mod, name)
                assert "soveryn_complete" not in str(value), f"{mod.__name__}.{name} still points at museum: {value}"
