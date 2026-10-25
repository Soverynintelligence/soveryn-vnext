"""Outage / blocked claims require a same-run probe record.

The pulse invented "build brain on 127.0.0.1:8080 is down" and blocked
Forge. These tests pin the structural gate: no probe → not reported and
does not block; a failing probe is reported with evidence; a passing
probe clears the claim.
"""

from __future__ import annotations

from soveryn.platform.inference.outage import (
    ProbeRecord,
    apply_outage_gate,
    evaluate_outage_claims,
    format_outage_report,
    merge_tick_probes,
    official_outages,
    should_block_dispatch,
)

INVENTED = (
    "build brain on 127.0.0.1:8080 is down; blocked Forge until it returns."
)
OK_DEEPSEEK = ProbeRecord(
    target="http://10.10.10.2:8888",
    timestamp="2026-10-25T13:50:00Z",
    result="ok",
    name="kernel_build",
    detail="deepseek HTTP 200 from http://10.10.10.2:8888/health",
)
FAIL_DEEPSEEK = ProbeRecord(
    target="http://10.10.10.2:8888",
    timestamp="2026-10-25T13:50:00Z",
    result="fail",
    name="kernel_build",
    detail="deepseek URLError: connection refused (http://10.10.10.2:8888/health)",
)


def test_invented_outage_with_no_probe_is_not_reported_or_acted_on():
    verdict = evaluate_outage_claims(INVENTED, probes=())
    assert verdict.reported == ()
    assert verdict.blocks_dispatch is False
    assert should_block_dispatch(()) is False
    assert "8080" not in verdict.text
    assert "blocked Forge" not in verdict.text
    assert verdict.unverified
    assert official_outages(()) == ()
    assert format_outage_report(()) == ""


def test_invented_8080_claim_does_not_match_the_real_brain_probe():
    """A guessed port is unverified even when the real brain was probed."""
    verdict = evaluate_outage_claims(INVENTED, probes=(OK_DEEPSEEK,))
    assert verdict.reported == ()
    assert verdict.blocks_dispatch is False
    assert "8080" not in verdict.text
    assert any("8080" in item for item in verdict.unverified)


def test_failing_probe_is_reported_with_evidence_and_blocks_dispatch():
    verdict = evaluate_outage_claims(
        "The kernel build brain is down; do not dispatch Forge.",
        probes=(FAIL_DEEPSEEK,),
    )
    assert verdict.blocks_dispatch is True
    assert len(verdict.reported) == 1
    row = verdict.reported[0]
    assert row["target"] == "http://10.10.10.2:8888"
    assert row["timestamp"] == "2026-10-25T13:50:00Z"
    assert row["result"] == "fail"
    assert "8888" in format_outage_report((FAIL_DEEPSEEK,))
    assert "2026-10-25T13:50:00Z" in format_outage_report((FAIL_DEEPSEEK,))
    assert "result=fail" in format_outage_report((FAIL_DEEPSEEK,))
    # Name-level claim matches the real target, so the sentence may stay;
    # the evidence is the probe record, not a guessed port.
    assert "8080" not in row["target"]


FAIL_DISPATCH = ProbeRecord(
    target="delegation.db",
    timestamp="2026-10-25T14:00:00Z",
    result="fail",
    name="delegation_dispatch",
    detail="ledger write did not persist; not sent",
)


def test_dispatch_failure_feeds_gate_unverified_never_blocks():
    """Ledger-write failures are probes. Invented 8080 still cannot block."""
    merged = merge_tick_probes((OK_DEEPSEEK,), (FAIL_DISPATCH,))
    verdict = apply_outage_gate(INVENTED, merged)
    assert any(row["name"] == "delegation_dispatch" for row in verdict.reported)
    assert any("8080" in item for item in verdict.unverified)
    assert "8080" not in verdict.text
    assert "blocked Forge" not in verdict.text
    # Block is the verified ledger miss, not the unverified outage sentence.
    assert verdict.blocks_dispatch is True
    assert should_block_dispatch(merged) is True

    ok_only = apply_outage_gate(INVENTED, merge_tick_probes((OK_DEEPSEEK,), ()))
    assert ok_only.blocks_dispatch is False
    assert ok_only.reported == ()
    assert should_block_dispatch(merge_tick_probes((OK_DEEPSEEK,), ())) is False


def test_passing_probe_clears_a_down_claim():
    verdict = evaluate_outage_claims(
        "The kernel build brain is down.",
        probes=(OK_DEEPSEEK,),
    )
    assert verdict.reported == ()
    assert verdict.blocks_dispatch is False
    assert "down" not in verdict.text.lower()
    assert format_outage_report((OK_DEEPSEEK,)) == ""


def test_gate_keeps_unrelated_note_text():
    note = "Quiet — nothing new. Lattice is calm."
    verdict = apply_outage_gate(note, probes=(OK_DEEPSEEK,))
    assert verdict.text == note
    assert verdict.blocks_dispatch is False


def test_heartbeat_drops_invented_outage_and_does_not_block(tmp_path, monkeypatch):
    """Wired through the pulse: invented 8080 never lands or blocks dispatch."""
    from soveryn.agents.heartbeat.thoughts_log import ThoughtsLog
    from tests.test_heartbeat_integration import (
        _ONE_MATERIAL,
        _make_daemon,
        _run_tick_with_fakes,
    )

    report = {
        "brain": "deepseek",
        "alias": "DeepSeek-V4.1-Flash-1017",
        "base_url": "http://10.10.10.2:8888",
        "status": "ok",
        "detail": "ok",
        "latency_ms": 1.0,
        "probed": True,
        "probed_at": "2026-10-25T13:50:00Z",
        "target": "http://10.10.10.2:8888",
        "probe": {
            "target": "http://10.10.10.2:8888",
            "timestamp": "2026-10-25T13:50:00Z",
            "result": "ok",
            "name": "kernel_build",
            "detail": "ok",
        },
    }
    monkeypatch.setattr(
        "soveryn.platform.inference.health.kernel_brain_health_report",
        lambda timeout=2.0: report,
    )
    tlog_path = tmp_path / "thoughts.jsonl"
    daemon = _make_daemon(tmp_path, thoughts_path=tlog_path)
    _run_tick_with_fakes(
        daemon,
        model_response=INVENTED + " Also the lattice is quiet.",
        material_signals=_ONE_MATERIAL,
    )
    rec = ThoughtsLog(tlog_path).last()
    assert rec is not None
    assert "8080" not in (rec.get("note") or "")
    assert rec.get("blocks_dispatch") is False
    assert rec.get("probes")
    assert rec["probes"][0]["target"] == "http://10.10.10.2:8888"
    assert rec["probes"][0]["result"] == "ok"
    assert rec.get("dispatch_probes") == []
    assert rec.get("unverified_outages")


def test_heartbeat_dispatch_failure_feeds_gate_and_keeps_receipt_keys(
    tmp_path, monkeypatch
):
    """Pulse receipt keeps PR1 keys plus dispatch_probes; 8080 stays unverified."""
    import json

    from soveryn.agents.heartbeat.thoughts_log import ThoughtsLog
    from tests.test_heartbeat_integration import (
        _ONE_MATERIAL,
        _make_daemon,
        _run_tick_with_fakes,
    )

    report = {
        "brain": "deepseek",
        "alias": "DeepSeek-V4.1-Flash-1017",
        "base_url": "http://10.10.10.2:8888",
        "status": "ok",
        "detail": "ok",
        "latency_ms": 1.0,
        "probed": True,
        "probed_at": "2026-10-25T13:50:00Z",
        "target": "http://10.10.10.2:8888",
        "probe": {
            "target": "http://10.10.10.2:8888",
            "timestamp": "2026-10-25T13:50:00Z",
            "result": "ok",
            "name": "kernel_build",
            "detail": "ok",
        },
    }
    monkeypatch.setattr(
        "soveryn.platform.inference.health.kernel_brain_health_report",
        lambda timeout=2.0: report,
    )
    probe_path = tmp_path / "dispatch_probes.jsonl"
    probe_path.write_text(json.dumps(FAIL_DISPATCH.as_dict()) + "\n", encoding="utf-8")
    monkeypatch.setenv("SOVERYN_DISPATCH_PROBES", str(probe_path))
    tlog_path = tmp_path / "thoughts.jsonl"
    daemon = _make_daemon(tmp_path, thoughts_path=tlog_path)
    _run_tick_with_fakes(
        daemon,
        model_response=INVENTED + " Also I sent 1f1f049d.",
        material_signals=_ONE_MATERIAL,
    )
    rec = ThoughtsLog(tlog_path).last()
    assert rec is not None
    assert "8080" not in (rec.get("note") or "")
    assert rec["probes"][0]["result"] == "ok"
    assert rec["dispatch_probes"]
    assert rec["dispatch_probes"][0]["name"] == "delegation_dispatch"
    assert rec["dispatch_probes"][0]["result"] == "fail"
    assert rec.get("blocks_dispatch") is True
    assert any("8080" in item for item in rec.get("unverified_outages") or [])


def test_heartbeat_failing_probe_is_recorded_with_evidence(tmp_path, monkeypatch):
    from soveryn.agents.heartbeat.thoughts_log import ThoughtsLog
    from tests.test_heartbeat_integration import _make_daemon, _run_tick_with_fakes

    report = {
        "brain": "deepseek",
        "alias": "DeepSeek-V4.1-Flash-1017",
        "base_url": "http://10.10.10.2:8888",
        "status": "fail",
        "detail": "connection refused",
        "latency_ms": 12.0,
        "probed": True,
        "probed_at": "2026-10-25T13:50:00Z",
        "target": "http://10.10.10.2:8888",
        "probe": {
            "target": "http://10.10.10.2:8888",
            "timestamp": "2026-10-25T13:50:00Z",
            "result": "fail",
            "name": "kernel_build",
            "detail": "connection refused",
        },
    }
    monkeypatch.setattr(
        "soveryn.platform.inference.health.kernel_brain_health_report",
        lambda timeout=2.0: report,
    )
    tlog_path = tmp_path / "thoughts.jsonl"
    daemon = _make_daemon(tmp_path, thoughts_path=tlog_path)
    _run_tick_with_fakes(
        daemon,
        model_response="The kernel build brain is down.",
        material_signals=[],
    )
    rec = ThoughtsLog(tlog_path).last()
    assert rec is not None
    assert rec.get("blocks_dispatch") is True
    assert rec["probes"][0]["result"] == "fail"
    assert rec["probes"][0]["target"] == "http://10.10.10.2:8888"
    assert rec["probes"][0]["timestamp"] == "2026-10-25T13:50:00Z"


def test_automation_live_run_drops_invented_outage(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from soveryn.automations.registry import AutomationSpec, Delivery
    from soveryn.automations.runner import run_automation

    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    spec = AutomationSpec(
        id="morning_brief",
        title="Morning Brief",
        category="news",
        agent="aetheria",
        cron="30 7 * * *",
        prompt="Compose the morning brief.",
        delivery=Delivery(channel="signal", target="jon"),
        enabled=True,
    )
    monkeypatch.setattr(
        "soveryn.automations.runner.get_automation", lambda _id: spec
    )
    monkeypatch.setattr(
        "soveryn.platform.inference.health.kernel_brain_health_report",
        lambda timeout=2.0: {
            "brain": "deepseek",
            "alias": "DeepSeek-V4.1-Flash-1017",
            "base_url": "http://10.10.10.2:8888",
            "status": "ok",
            "detail": "ok",
            "latency_ms": 1.0,
            "probed": True,
            "probed_at": "2026-10-25T13:50:00Z",
            "target": "http://10.10.10.2:8888",
            "probe": OK_DEEPSEEK.as_dict(),
        },
    )
    monkeypatch.setattr(
        "soveryn.platform.inference.health.format_kernel_brain_health_block",
        lambda timeout=2.0, report=None: "probe block\n",
    )

    class _Loop:
        def process_message(self, session_id, prompt, source="automation"):
            return SimpleNamespace(
                content=INVENTED,
                finish_reason="stop",
                tool_calls=None,
                usage=None,
                context_usage=None,
            )

    class _Store:
        def list_sessions(self, agent=None, limit=200):
            return []

        def new_session(self, agent, title=""):
            return "sid-auto"

    result = run_automation(
        "morning_brief",
        dry_run=False,
        agent_loop=_Loop(),
        conv_store=_Store(),
    )
    assert result["status"] == "ok"
    assert "8080" not in str(result.get("content") or "")
    assert result.get("blocks_dispatch") is False
    assert result.get("outage", {}).get("reported") == []
