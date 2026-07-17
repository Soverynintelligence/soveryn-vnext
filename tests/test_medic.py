import importlib
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
                     state={}, now=1000.0)
    assert len(d) == 1 and d[0].action == "act" and d[0].unit == "soveryn-embeddings.service"


def test_within_cooldown_is_skipped():
    state = {"embeddings": {"consecutive_fails": 1, "last_restart_ts": 900.0, "escalated": False}}
    d = medic.decide(unhealthy_keys={"embeddings"}, router_healthy=True,
                     state=state, now=1000.0)  # 100 < 300
    assert d[0].action == "skip_cooldown"


def test_cooldown_is_per_target_not_global():
    # embeddings cooling, heartbeat not → heartbeat still acts.
    state = {"embeddings": {"consecutive_fails": 1, "last_restart_ts": 990.0, "escalated": False}}
    d = medic.decide(unhealthy_keys={"embeddings", "heartbeat"}, router_healthy=True,
                     state=state, now=1000.0)
    by_key = {x.key: x for x in d}
    assert by_key["embeddings"].action == "skip_cooldown"
    assert by_key["heartbeat"].action == "act"


def test_loopguard_trips_to_escalate():
    state = {"vnext": {"consecutive_fails": 3, "last_restart_ts": 700.0, "escalated": False}}
    d = medic.decide(unhealthy_keys={"vnext"}, router_healthy=True,
                     state=state, now=800.0)
    assert d[0].action == "escalate"
    assert d[0].priority is True  # vnext escalation is night-pageable


def test_non_critical_escalation_is_not_priority():
    state = {"embeddings": {"consecutive_fails": 3, "last_restart_ts": 700.0, "escalated": False}}
    d = medic.decide(unhealthy_keys={"embeddings"}, router_healthy=True,
                     state=state, now=800.0)
    assert d[0].action == "escalate" and d[0].priority is False


def test_escalated_target_is_latched():
    state = {"embeddings": {"consecutive_fails": 3, "last_restart_ts": 700.0, "escalated": True}}
    d = medic.decide(unhealthy_keys={"embeddings"}, router_healthy=True,
                     state=state, now=800.0)
    assert d[0].action == "skip_escalated"


def test_vnext_deferred_when_router_unhealthy():
    d = medic.decide(unhealthy_keys={"vnext"}, router_healthy=False,
                     state={}, now=1000.0)
    assert d[0].action == "skip_router_down"


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


def test_run_once_acts_and_records_state(tmp_path, monkeypatch):
    monkeypatch.setattr(medic, "STATE_DIR", tmp_path)
    monkeypatch.setattr(medic, "STATE_FILE", tmp_path / "medic_state.json")
    monkeypatch.setattr(medic, "LOG_FILE", tmp_path / "medic.jsonl")
    # everything healthy except embeddings
    monkeypatch.setattr(medic, "_probe", lambda: ({"embeddings"}, True))
    calls = []
    monkeypatch.setattr(medic, "_run_unit", lambda unit, verb: calls.append((unit, verb)))
    monkeypatch.setattr(medic, "_escalate", lambda d: calls.append(("ESCALATE", d.unit)))

    result = medic.run_once(now=1000.0)

    assert ("soveryn-embeddings.service", "restart") in calls
    assert result["actions"][0]["action"] == "act"
    state = medic._read_state()
    assert state["embeddings"]["consecutive_fails"] == 1
    assert state["embeddings"]["last_restart_ts"] == 1000.0


def test_run_once_escalates_and_does_not_restart_when_loopguard_tripped(tmp_path, monkeypatch):
    monkeypatch.setattr(medic, "STATE_DIR", tmp_path)
    monkeypatch.setattr(medic, "STATE_FILE", tmp_path / "medic_state.json")
    monkeypatch.setattr(medic, "LOG_FILE", tmp_path / "medic.jsonl")
    (tmp_path / "medic_state.json").write_text(json.dumps(
        {"vnext": {"consecutive_fails": 3, "last_restart_ts": 700.0, "escalated": False}}))
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
    monkeypatch.setattr(medic, "STATE_FILE", tmp_path / "medic_state.json")
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
    monkeypatch.setattr(medic, "STATE_FILE", tmp_path / "medic_state.json")
    monkeypatch.setattr(medic, "LOG_FILE", tmp_path / "medic.jsonl")
    monkeypatch.setattr(medic, "_probe", lambda: ({"embeddings"}, True))

    def boom(unit, verb):
        raise RuntimeError("systemctl failed")

    monkeypatch.setattr(medic, "_run_unit", boom)
    monkeypatch.setattr(medic, "_escalate", lambda d: None)

    result = medic.run_once(now=1000.0)  # must NOT raise

    # audit line written despite the failure
    assert (tmp_path / "medic.jsonl").read_text().strip() != ""
    # the failed attempt was still recorded to state (paces retries / feeds loop-guard)
    state = medic._read_state()
    assert state["embeddings"]["consecutive_fails"] == 1
    # the action reflects the failure
    assert result["actions"][0]["ok"] is False


def test_run_once_survives_a_failed_escalation(tmp_path, monkeypatch):
    monkeypatch.setattr(medic, "STATE_DIR", tmp_path)
    monkeypatch.setattr(medic, "STATE_FILE", tmp_path / "medic_state.json")
    monkeypatch.setattr(medic, "LOG_FILE", tmp_path / "medic.jsonl")
    (tmp_path / "medic_state.json").write_text(json.dumps(
        {"embeddings": {"consecutive_fails": 3, "last_restart_ts": 700.0, "escalated": False}}))
    monkeypatch.setattr(medic, "_probe", lambda: ({"embeddings"}, True))

    def boom(decision):
        raise RuntimeError("signal send failed")

    monkeypatch.setattr(medic, "_escalate", boom)
    monkeypatch.setattr(medic, "_run_unit", lambda unit, verb: None)

    result = medic.run_once(now=1000.0)  # must NOT raise

    assert (tmp_path / "medic.jsonl").read_text().strip() != ""
    state = medic._read_state()
    assert state["embeddings"]["escalated"] is True
    assert result["actions"][0]["ok"] is False


def test_run_once_clears_state_on_recovery(tmp_path, monkeypatch):
    monkeypatch.setattr(medic, "STATE_DIR", tmp_path)
    monkeypatch.setattr(medic, "STATE_FILE", tmp_path / "medic_state.json")
    monkeypatch.setattr(medic, "LOG_FILE", tmp_path / "medic.jsonl")
    (tmp_path / "medic_state.json").write_text(json.dumps(
        {"embeddings": {"consecutive_fails": 2, "last_restart_ts": 700.0, "escalated": False}}))
    # embeddings is healthy now — not in the unhealthy set returned by probe.
    monkeypatch.setattr(medic, "_probe", lambda: (set(), True))
    monkeypatch.setattr(medic, "_run_unit", lambda unit, verb: None)
    monkeypatch.setattr(medic, "_escalate", lambda d: None)

    medic.run_once(now=1000.0)

    state = medic._read_state()
    assert "embeddings" not in state


def test_converges_no_infinite_restart():
    # Regression test for the Critical convergence bug: a target with a 600s
    # cooldown (e.g. heartbeat) that stays unhealthy forever must NOT restart
    # forever — it must escalate after LOOPGUARD_MAX attempts and then latch
    # into skip_escalated, bounding total act count at LOOPGUARD_MAX no matter
    # how many further ticks are simulated.
    state: dict[str, dict] = {}
    now = 0.0
    act_count = 0
    escalate_count = 0
    skip_escalated_seen = False

    for _tick in range(50):  # far more ticks than LOOPGUARD_MAX
        decisions = medic.decide(unhealthy_keys={"heartbeat"}, router_healthy=True,
                                 state=state, now=now)
        d = decisions[0]
        st = state.setdefault("heartbeat", medic._blank_state())
        if d.action == "act":
            act_count += 1
            st["consecutive_fails"] += 1
            st["last_restart_ts"] = now
        elif d.action == "escalate":
            escalate_count += 1
            st["escalated"] = True
        elif d.action == "skip_escalated":
            skip_escalated_seen = True
        # advance past the target's cooldown each step so a real window-based
        # bug (which re-arms on aged-out entries) would keep acting forever.
        now += medic.TARGETS["heartbeat"].cooldown_s + 1.0

    assert act_count == medic.LOOPGUARD_MAX
    assert escalate_count == 1
    assert skip_escalated_seen is True


def test_module_main_runs_one_tick(monkeypatch):
    called = {}
    monkeypatch.setattr(medic, "run_once", lambda: called.setdefault("ran", True) or {"actions": []})
    main_mod = importlib.import_module("soveryn.platform.medic.__main__")
    main_mod.main()
    assert called.get("ran") is True


def test_service_unit_targets_the_module_and_soveryn_python():
    text = open("runtime/soveryn-medic.service").read()
    assert "python -m soveryn.platform.medic" in text
    assert "/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python" in text
    assert "Type=oneshot" in text


def test_timer_unit_ticks_every_60s():
    text = open("runtime/soveryn-medic.timer").read()
    assert "OnUnitActiveSec=60" in text
    assert "Unit=soveryn-medic.service" in text
