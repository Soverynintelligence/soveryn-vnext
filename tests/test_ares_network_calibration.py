"""Ares network-lane calibration (2026-06-18).

The unprivileged daemon's live `ss` showed: 6 EMERGENCY public-listener
findings that were actually 4 Tailscale-interface listeners (private tailnet,
not public) + SSH on 0.0.0.0:22 (expected) — all with EMPTY process (Ares is
process-blind without root). Six false alarms bury a real exposure. These
tests pin the calibrated behaviour: tailnet = recorded-not-alarmed, expected
ports allowlisted even when process-blind, but a genuine public listener still
fires EMERGENCY.
"""
from soveryn.agents.ares.findings import Severity
from soveryn.agents.ares.lanes.network import NetworkAllowList, collect_listeners


def _allow() -> NetworkAllowList:
    # Defaults: loopback allowlist, public "22:sshd", tailnet ranges.
    return NetworkAllowList.from_env({})


def test_tailnet_listeners_are_info_not_emergency():
    # Production reality: tailnet binds, process unreadable (no users:(()) tuple).
    ss = (
        "LISTEN 0 4096 100.71.129.32:443 0.0.0.0:*\n"
        "LISTEN 0 4096 [fd7a:115c:a1e0::cd37:8120]:41925 [::]:*\n"
    )
    findings = collect_listeners(ss, allow_list=_allow())
    assert findings, "tailnet listeners should still be RECORDED (visible on review)"
    assert all(f.finding_type == "network.tailnet_listener" for f in findings)
    assert all(f.severity == Severity.INFO for f in findings)
    assert not any(f.severity == Severity.EMERGENCY for f in findings)


def test_ssh22_allowlisted_even_when_process_blind():
    # Ares unprivileged → no process in ss. Port-fallback must still allowlist 22.
    findings = collect_listeners("LISTEN 0 128 0.0.0.0:22 0.0.0.0:*\n", allow_list=_allow())
    assert findings == [], f"SSH:22 should be allowlisted via port-fallback, got {findings}"


def test_genuine_public_still_emergency_when_process_blind():
    # A real unallowlisted public port, process unreadable → STILL EMERGENCY.
    findings = collect_listeners("LISTEN 0 128 0.0.0.0:4444 0.0.0.0:*\n", allow_list=_allow())
    assert len(findings) == 1
    assert findings[0].severity == Severity.EMERGENCY
    assert findings[0].finding_type == "network.public_listener_unallowlisted"


def test_real_public_ip_is_not_treated_as_tailnet():
    # A non-tailnet public IP must NOT be downgraded — security preserved.
    findings = collect_listeners("LISTEN 0 128 203.0.113.5:9000 0.0.0.0:*\n", allow_list=_allow())
    assert len(findings) == 1
    assert findings[0].severity == Severity.EMERGENCY


def test_known_process_still_precise():
    # When the process IS visible (privileged ss / tests), keep exact matching:
    # sshd on 22 = allowed; nc on 22 = EMERGENCY.
    ok = collect_listeners('LISTEN 0 128 0.0.0.0:22 0.0.0.0:* users:(("sshd",pid=900,fd=3))\n', allow_list=_allow())
    assert ok == []
    bad = collect_listeners('LISTEN 0 128 0.0.0.0:22 0.0.0.0:* users:(("nc",pid=900,fd=3))\n', allow_list=_allow())
    assert len(bad) == 1 and bad[0].severity == Severity.EMERGENCY
