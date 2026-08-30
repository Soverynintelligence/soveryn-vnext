import importlib
import json
import sqlite3
from datetime import datetime

import pytest

from soveryn.platform.medic import medic


def _make_heartbeat_log_db(tmp_path, rows):
    """rows: list of dicts with at least 'triggered_at'; other cols default."""
    db_path = tmp_path / "lattice_vnext.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE heartbeat_log(
            id TEXT, triggered_at TEXT, completed_at TEXT, eligible INT,
            skip_reason TEXT, action_taken INT, tool_call_count INT,
            response_length INT, error TEXT, dry_run INT, surfaced_to_chat INT
        )"""
    )
    for row in rows:
        conn.execute(
            "INSERT INTO heartbeat_log (id, triggered_at, eligible, skip_reason) "
            "VALUES (?, ?, ?, ?)",
            (row.get("id", "x"), row["triggered_at"], row.get("eligible", 1),
             row.get("skip_reason")),
        )
    conn.commit()
    conn.close()
    return db_path


def test_no_target_is_a_router_unit():
    # HARD SAFETY INVARIANT: the medic must never be able to restart a router.
    target_units = {t.unit for t in medic.TARGETS.values()}
    assert medic.FORBIDDEN_UNITS.isdisjoint(target_units)
    assert "soveryn-router.service" in medic.FORBIDDEN_UNITS
    assert "soveryn-router-quadro.service" in medic.FORBIDDEN_UNITS


def test_unhealthy_target_out_of_cooldown_acts():
    d = medic.decide(unhealthy_keys={"dream"}, router_healthy=True,
                     state={}, now=1000.0)
    assert len(d) == 1 and d[0].action == "act" and d[0].unit == "soveryn-dream.service"


def test_within_cooldown_is_skipped():
    state = {"dream": {"consecutive_fails": 1, "last_restart_ts": 900.0, "escalated": False}}
    d = medic.decide(unhealthy_keys={"dream"}, router_healthy=True,
                     state=state, now=1000.0)  # 100 < 300
    assert d[0].action == "skip_cooldown"


def test_cooldown_is_per_target_not_global():
    # dream cooling, heartbeat not → heartbeat still acts.
    state = {"dream": {"consecutive_fails": 1, "last_restart_ts": 990.0, "escalated": False}}
    d = medic.decide(unhealthy_keys={"dream", "heartbeat"}, router_healthy=True,
                     state=state, now=1000.0)
    by_key = {x.key: x for x in d}
    assert by_key["dream"].action == "skip_cooldown"
    assert by_key["heartbeat"].action == "act"


def test_loopguard_trips_to_escalate():
    state = {"vnext": {"consecutive_fails": 3, "last_restart_ts": 700.0, "escalated": False}}
    d = medic.decide(unhealthy_keys={"vnext"}, router_healthy=True,
                     state=state, now=800.0)
    assert d[0].action == "escalate"
    assert d[0].priority is True  # vnext escalation is night-pageable


def test_non_critical_escalation_is_not_priority():
    state = {"dream": {"consecutive_fails": 3, "last_restart_ts": 700.0, "escalated": False}}
    d = medic.decide(unhealthy_keys={"dream"}, router_healthy=True,
                     state=state, now=800.0)
    assert d[0].action == "escalate" and d[0].priority is False


def test_escalated_target_is_latched():
    state = {"dream": {"consecutive_fails": 3, "last_restart_ts": 700.0, "escalated": True}}
    d = medic.decide(unhealthy_keys={"dream"}, router_healthy=True,
                     state=state, now=800.0)
    assert d[0].action == "skip_escalated"


def test_unknown_remote_escalates_once_then_latches():
    d = medic.decide(unhealthy_keys={"spark-embed"}, router_healthy=True,
                     state={}, now=1000.0)
    assert d[0].action == "escalate" and d[0].unit == "remote"
    d2 = medic.decide(
        unhealthy_keys={"spark-embed"}, router_healthy=True,
        state={"spark-embed": {"consecutive_fails": 0, "last_restart_ts": None, "escalated": True}},
        now=1060.0,
    )
    assert d2[0].action == "skip_escalated"


def test_vnext_deferred_when_router_unhealthy():
    d = medic.decide(unhealthy_keys={"vnext"}, router_healthy=False,
                     state={}, now=1000.0)
    assert d[0].action == "skip_router_down"


def test_probe_unhealthy_classifies_from_readings():
    unhealthy, router_healthy = medic.probe_unhealthy(
        http_ok={"vnext": False, "router": True},
        unit_active={"dream": False, "x-feed": True, "parakeet": True,
                     "vett-patrol": True, "representation": True},
        heartbeat_age=100.0,           # fresh
        comfyui_on_her_card=False,
    )
    assert unhealthy == {"vnext", "dream"}
    assert router_healthy is True


def test_probe_flags_local_embed():
    unhealthy, _ = medic.probe_unhealthy(
        http_ok={"vnext": True, "embeddings": False, "router": True},
        unit_active={"dream": True, "x-feed": True, "parakeet": True,
                     "vett-patrol": True, "representation": True},
        heartbeat_age=100.0,
        comfyui_on_her_card=False,
    )
    assert "embeddings" in unhealthy


def test_probe_flags_stale_heartbeat_and_comfyui_squatter():
    unhealthy, _ = medic.probe_unhealthy(
        http_ok={"vnext": True, "router": True},
        unit_active={"dream": True, "x-feed": True, "parakeet": True,
                     "vett-patrol": True, "representation": True},
        heartbeat_age=3000.0,          # > 2400 → stale
        comfyui_on_her_card=True,
    )
    assert "heartbeat" in unhealthy and "comfyui" in unhealthy


def test_heartbeat_age_fresh_when_recent_tick(tmp_path):
    ts = "2026-07-18T08:20:58.532907"
    now = datetime.fromisoformat(ts).timestamp() + 300  # ~5 min later
    db = _make_heartbeat_log_db(tmp_path, [{"triggered_at": ts, "eligible": 1}])
    age = medic._heartbeat_age(now, db_path=db)
    assert 295 <= age <= 305
    assert age < medic.HEARTBEAT_MAX_AGE_S


def test_heartbeat_age_fresh_when_recent_tick_is_a_quiet_hours_skip(tmp_path):
    # THE regression test: a resting (quiet-hours-skipped) but recently-ticked
    # heartbeat must read as ALIVE, not stale. This is the exact case that
    # false-flagged and triggered 3 needless restarts + a suppressed escalation.
    ts = "2026-07-18T03:00:12.000000"
    now = datetime.fromisoformat(ts).timestamp() + 600  # ~10 min later
    db = _make_heartbeat_log_db(
        tmp_path, [{"triggered_at": ts, "eligible": 0, "skip_reason": "quiet_hours"}]
    )
    age = medic._heartbeat_age(now, db_path=db)
    assert 595 <= age <= 605
    assert age < medic.HEARTBEAT_MAX_AGE_S


def test_heartbeat_age_stale_when_no_tick_past_threshold(tmp_path):
    ts = "2026-07-18T08:20:58.532907"
    now = datetime.fromisoformat(ts).timestamp() + 3000  # 50 min later
    db = _make_heartbeat_log_db(tmp_path, [{"triggered_at": ts, "eligible": 0,
                                            "skip_reason": "quiet_hours"}])
    age = medic._heartbeat_age(now, db_path=db)
    assert age > medic.HEARTBEAT_MAX_AGE_S


def test_heartbeat_age_safe_on_missing_db(tmp_path):
    missing = tmp_path / "does_not_exist.db"
    assert medic._heartbeat_age(1000.0, db_path=missing) == 0.0


def test_heartbeat_age_safe_on_empty_table(tmp_path):
    db = _make_heartbeat_log_db(tmp_path, [])
    assert medic._heartbeat_age(1000.0, db_path=db) == 0.0


def test_run_once_acts_and_records_state(tmp_path, monkeypatch):
    monkeypatch.setattr(medic, "STATE_DIR", tmp_path)
    monkeypatch.setattr(medic, "STATE_FILE", tmp_path / "medic_state.json")
    monkeypatch.setattr(medic, "LOG_FILE", tmp_path / "medic.jsonl")
    # everything healthy except dream
    monkeypatch.setattr(medic, "_probe", lambda: ({"dream"}, True))
    calls = []
    monkeypatch.setattr(medic, "_run_unit", lambda unit, verb: calls.append((unit, verb)))
    monkeypatch.setattr(medic, "_escalate", lambda d: calls.append(("ESCALATE", d.unit)))

    result = medic.run_once(now=1000.0)

    assert ("soveryn-dream.service", "restart") in calls
    assert result["actions"][0]["action"] == "act"
    state = medic._read_state()
    assert state["dream"]["consecutive_fails"] == 1
    assert state["dream"]["last_restart_ts"] == 1000.0


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
    monkeypatch.setattr(medic, "_probe", lambda: ({"dream"}, True))

    def boom(unit, verb):
        raise RuntimeError("systemctl failed")

    monkeypatch.setattr(medic, "_run_unit", boom)
    monkeypatch.setattr(medic, "_escalate", lambda d: None)

    result = medic.run_once(now=1000.0)  # must NOT raise

    # audit line written despite the failure
    assert (tmp_path / "medic.jsonl").read_text().strip() != ""
    # the failed attempt was still recorded to state (paces retries / feeds loop-guard)
    state = medic._read_state()
    assert state["dream"]["consecutive_fails"] == 1
    # the action reflects the failure
    assert result["actions"][0]["ok"] is False


def test_run_once_survives_a_failed_escalation(tmp_path, monkeypatch):
    monkeypatch.setattr(medic, "STATE_DIR", tmp_path)
    monkeypatch.setattr(medic, "STATE_FILE", tmp_path / "medic_state.json")
    monkeypatch.setattr(medic, "LOG_FILE", tmp_path / "medic.jsonl")
    (tmp_path / "medic_state.json").write_text(json.dumps(
        {"dream": {"consecutive_fails": 3, "last_restart_ts": 700.0, "escalated": False}}))
    monkeypatch.setattr(medic, "_probe", lambda: ({"dream"}, True))

    def boom(decision):
        raise RuntimeError("signal send failed")

    monkeypatch.setattr(medic, "_escalate", boom)
    monkeypatch.setattr(medic, "_run_unit", lambda unit, verb: None)

    result = medic.run_once(now=1000.0)  # must NOT raise

    assert (tmp_path / "medic.jsonl").read_text().strip() != ""
    state = medic._read_state()
    assert state["dream"]["escalated"] is True
    assert result["actions"][0]["ok"] is False


def test_run_once_clears_state_on_recovery(tmp_path, monkeypatch):
    monkeypatch.setattr(medic, "STATE_DIR", tmp_path)
    monkeypatch.setattr(medic, "STATE_FILE", tmp_path / "medic_state.json")
    monkeypatch.setattr(medic, "LOG_FILE", tmp_path / "medic.jsonl")
    (tmp_path / "medic_state.json").write_text(json.dumps(
        {"dream": {"consecutive_fails": 2, "last_restart_ts": 700.0, "escalated": False}}))
    # dream is healthy now — not in the unhealthy set returned by probe.
    monkeypatch.setattr(medic, "_probe", lambda: (set(), True))
    monkeypatch.setattr(medic, "_run_unit", lambda unit, verb: None)
    monkeypatch.setattr(medic, "_escalate", lambda d: None)

    medic.run_once(now=1000.0)

    state = medic._read_state()
    assert "dream" not in state


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


def test_tg_bridge_is_not_resurrectable():
    """A retired service must not be on the medic's watch list.

    2026-08-07: Telegram was replaced by Signal, and the bridge had been logging
    91,560 HTTP 409s in seven days — the Claude Code telegram plugin polls the
    same bot token, and Telegram allows exactly one getUpdates consumer.

    `systemctl --user disable --now` did not hold. The medic saw a stopped unit,
    classified it unhealthy, and restarted it 42 seconds later:

        08:46:06  Stopped soveryn-tg-bridge.service
        08:46:48  Started soveryn-tg-bridge.service
                  {"unhealthy": ["tg-bridge"], "actions": [{"action": "act", ...

    That is the medic working correctly — it cannot distinguish "deliberately
    retired" from "crashed." The watch list is the only place that distinction
    can live, so re-adding tg-bridge would silently resurrect a dead service
    and restart the 409 storm.
    """
    assert "tg-bridge" not in medic.TARGETS
    assert "tg-bridge" not in medic._UNIT_KEYS
    assert not any("tg-bridge" in t.unit for t in medic.TARGETS.values())


def test_spark_embed_is_not_watchable():
    """Spark soveryn-embed stays parked; tower librarian is the watch target.

    GLM owns Spark UMA. Medic must not GET 10.10.10.2:8096. The helper-Quadro
    unit soveryn-embeddings.service is the healable embeddings surface.
    """
    assert medic.TARGETS["embeddings"].unit == "soveryn-embeddings.service"
    assert medic._HTTP_URLS.get("embeddings") == "http://127.0.0.1:8096/health"
    assert "10.10.10.2:8096" not in medic._HTTP_URLS.values()
    assert "embeddings" not in medic._UNIT_KEYS
