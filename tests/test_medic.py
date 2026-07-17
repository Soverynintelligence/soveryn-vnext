from soveryn.platform.medic import medic


def test_no_target_is_a_router_unit():
    # HARD SAFETY INVARIANT: the medic must never be able to restart a router.
    target_units = {t.unit for t in medic.TARGETS.values()}
    assert medic.FORBIDDEN_UNITS.isdisjoint(target_units)
    assert "soveryn-router.service" in medic.FORBIDDEN_UNITS
    assert "soveryn-router-quadro.service" in medic.FORBIDDEN_UNITS


def test_unhealthy_target_out_of_cooldown_acts():
    d = medic.decide(unhealthy_keys={"embeddings"}, router_healthy=True,
                     restart_history={}, now=1000.0)
    assert len(d) == 1 and d[0].action == "act" and d[0].unit == "soveryn-embeddings.service"


def test_within_cooldown_is_skipped():
    d = medic.decide(unhealthy_keys={"embeddings"}, router_healthy=True,
                     restart_history={"embeddings": [900.0]}, now=1000.0)  # 100 < 300
    assert d[0].action == "skip_cooldown"


def test_cooldown_is_per_target_not_global():
    # embeddings cooling, heartbeat not → heartbeat still acts.
    d = medic.decide(unhealthy_keys={"embeddings", "heartbeat"}, router_healthy=True,
                     restart_history={"embeddings": [990.0]}, now=1000.0)
    by_key = {x.key: x for x in d}
    assert by_key["embeddings"].action == "skip_cooldown"
    assert by_key["heartbeat"].action == "act"


def test_loopguard_trips_to_escalate():
    hist = {"vnext": [100.0, 400.0, 700.0]}  # 3 restarts within 900s of now=800
    d = medic.decide(unhealthy_keys={"vnext"}, router_healthy=True,
                     restart_history=hist, now=800.0)
    assert d[0].action == "escalate"
    assert d[0].priority is True  # vnext escalation is night-pageable


def test_loopguard_window_expires():
    hist = {"embeddings": [0.0, 10.0, 20.0]}  # all older than 900s at now=2000
    d = medic.decide(unhealthy_keys={"embeddings"}, router_healthy=True,
                     restart_history=hist, now=2000.0)
    assert d[0].action == "act"


def test_vnext_deferred_when_router_unhealthy():
    d = medic.decide(unhealthy_keys={"vnext"}, router_healthy=False,
                     restart_history={}, now=1000.0)
    assert d[0].action == "skip_router_down"


def test_non_critical_escalation_is_not_priority():
    hist = {"embeddings": [100.0, 400.0, 700.0]}
    d = medic.decide(unhealthy_keys={"embeddings"}, router_healthy=True,
                     restart_history=hist, now=800.0)
    assert d[0].action == "escalate" and d[0].priority is False
