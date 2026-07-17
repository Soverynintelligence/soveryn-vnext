import json

import pytest

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


def test_probe_unhealthy_classifies_from_readings():
    unhealthy, router_healthy = medic.probe_unhealthy(
        http_ok={"vnext": False, "embeddings": True, "router": True},
        unit_active={"dream": False, "x-feed": True, "tg-bridge": True, "parakeet": True,
                     "vett-patrol": True, "representation": True},
        heartbeat_age=100.0,           # fresh
        comfyui_on_her_card=False,
    )
    assert unhealthy == {"vnext", "dream"}
    assert router_healthy is True


def test_probe_flags_stale_heartbeat_and_comfyui_squatter():
    unhealthy, _ = medic.probe_unhealthy(
        http_ok={"vnext": True, "embeddings": True, "router": True},
        unit_active={"dream": True, "x-feed": True, "tg-bridge": True, "parakeet": True,
                     "vett-patrol": True, "representation": True},
        heartbeat_age=3000.0,          # > 2400 → stale
        comfyui_on_her_card=True,
    )
    assert "heartbeat" in unhealthy and "comfyui" in unhealthy


def test_run_once_acts_and_records_history(tmp_path, monkeypatch):
    monkeypatch.setattr(medic, "STATE_DIR", tmp_path)
    monkeypatch.setattr(medic, "HISTORY_FILE", tmp_path / "restart_history.json")
    monkeypatch.setattr(medic, "LOG_FILE", tmp_path / "medic.jsonl")
    # everything healthy except embeddings
    monkeypatch.setattr(medic, "_probe", lambda: ({"embeddings"}, True))
    calls = []
    monkeypatch.setattr(medic, "_run_unit", lambda unit, verb: calls.append((unit, verb)))
    monkeypatch.setattr(medic, "_escalate", lambda d: calls.append(("ESCALATE", d.unit)))

    result = medic.run_once(now=1000.0)

    assert ("soveryn-embeddings.service", "restart") in calls
    assert result["actions"][0]["action"] == "act"
    hist = json.loads((tmp_path / "restart_history.json").read_text())
    assert hist["embeddings"] == [1000.0]


def test_run_once_escalates_and_does_not_restart_when_loopguard_tripped(tmp_path, monkeypatch):
    monkeypatch.setattr(medic, "STATE_DIR", tmp_path)
    monkeypatch.setattr(medic, "HISTORY_FILE", tmp_path / "restart_history.json")
    monkeypatch.setattr(medic, "LOG_FILE", tmp_path / "medic.jsonl")
    (tmp_path / "restart_history.json").write_text(json.dumps({"vnext": [100.0, 400.0, 700.0]}))
    monkeypatch.setattr(medic, "_probe", lambda: ({"vnext"}, True))
    calls = []
    monkeypatch.setattr(medic, "_run_unit", lambda unit, verb: calls.append(("RESTART", unit)))
    monkeypatch.setattr(medic, "_escalate", lambda d: calls.append(("ESCALATE", d.unit)))

    medic.run_once(now=800.0)

    assert ("ESCALATE", "soveryn-vnext.service") in calls
    assert ("RESTART", "soveryn-vnext.service") not in calls


def test_run_once_never_calls_run_unit_on_a_router(tmp_path, monkeypatch):
    # Defense in depth: even if a router key were somehow unhealthy, no router
    # unit can reach _run_unit (there is no router target).
    monkeypatch.setattr(medic, "STATE_DIR", tmp_path)
    monkeypatch.setattr(medic, "HISTORY_FILE", tmp_path / "restart_history.json")
    monkeypatch.setattr(medic, "LOG_FILE", tmp_path / "medic.jsonl")
    monkeypatch.setattr(medic, "_probe", lambda: (set(medic.TARGETS), True))
    restarted = []
    monkeypatch.setattr(medic, "_run_unit", lambda unit, verb: restarted.append(unit))
    monkeypatch.setattr(medic, "_escalate", lambda d: None)
    medic.run_once(now=5000.0)
    assert not (medic.FORBIDDEN_UNITS & set(restarted))


def test_run_unit_refuses_a_forbidden_router_unit():
    with pytest.raises(AssertionError):
        medic._run_unit("soveryn-router.service", "restart")
    with pytest.raises(AssertionError):
        medic._run_unit("soveryn-router-quadro.service", "restart")


def test_run_once_survives_a_failed_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(medic, "STATE_DIR", tmp_path)
    monkeypatch.setattr(medic, "HISTORY_FILE", tmp_path / "restart_history.json")
    monkeypatch.setattr(medic, "LOG_FILE", tmp_path / "medic.jsonl")
    monkeypatch.setattr(medic, "_probe", lambda: ({"embeddings"}, True))

    def boom(unit, verb):
        raise RuntimeError("systemctl failed")

    monkeypatch.setattr(medic, "_run_unit", boom)
    monkeypatch.setattr(medic, "_escalate", lambda d: None)

    result = medic.run_once(now=1000.0)  # must NOT raise

    # audit line written despite the failure
    assert (tmp_path / "medic.jsonl").read_text().strip() != ""
    # the failed attempt was still recorded to history (paces retries / feeds loop-guard)
    hist = json.loads((tmp_path / "restart_history.json").read_text())
    assert hist["embeddings"] == [1000.0]
    # the action reflects the failure
    assert result["actions"][0]["ok"] is False
