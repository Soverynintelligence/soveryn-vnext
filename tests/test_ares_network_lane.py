"""Fixture-driven tests for Ares network lane collectors."""

from soveryn.agents.ares.findings import Severity
from soveryn.agents.ares.lanes.network import (
    ExpectedServices,
    NetworkAllowList,
    collect_listeners,
    collect_service_presence,
    is_loopback_address,
)


HEALTHY_FIXTURE = (
    'LISTEN 0      4096   127.0.0.1:5001       0.0.0.0:*  users:(("python3.11",pid=413042,fd=8))\n'
    'LISTEN 0      4096   127.0.0.1:8090       0.0.0.0:*  users:(("llama-server",pid=109771,fd=12))\n'
    'LISTEN 0      128    0.0.0.0:22           0.0.0.0:*  users:(("sshd",pid=900,fd=3))\n'
)

PUBLIC_INTRUDER_FIXTURE = (
    'LISTEN 0      4096   127.0.0.1:5001       0.0.0.0:*  users:(("python3.11",pid=413042,fd=8))\n'
    'LISTEN 0      128    0.0.0.0:4444         0.0.0.0:*  users:(("nc",pid=99999,fd=3))\n'
)

NEW_LOCAL_LISTENER_FIXTURE = (
    'LISTEN 0      4096   127.0.0.1:5001       0.0.0.0:*  users:(("python3.11",pid=413042,fd=8))\n'
    'LISTEN 0      128    127.0.0.1:9999       0.0.0.0:*  users:(("python3.11",pid=123,fd=4))\n'
)


def _allowlist() -> NetworkAllowList:
    return NetworkAllowList(
        loopback_ports=frozenset({5001, 8090, 8087, 47017}),
        loopback_process_names=frozenset({"llama-server"}),
        public_ports=frozenset({(22, "sshd")}),
    )


def test_healthy_baseline_emits_no_findings():
    findings = collect_listeners(HEALTHY_FIXTURE, allow_list=_allowlist())
    assert findings == []


def test_public_unallowlisted_listener_is_emergency():
    findings = collect_listeners(PUBLIC_INTRUDER_FIXTURE, allow_list=_allowlist())
    emergencies = [f for f in findings if f.severity == Severity.EMERGENCY]
    assert len(emergencies) == 1
    f = emergencies[0]
    assert f.finding_type == "network.public_listener_unallowlisted"
    assert f.evidence["bind_address"] == "0.0.0.0"
    assert f.evidence["port"] == 4444
    assert f.evidence["process"] == "nc"


def test_public_allowlist_requires_matching_process():
    fixture = (
        'LISTEN 0      128    0.0.0.0:22           0.0.0.0:*  users:(("nc",pid=900,fd=3))\n'
    )
    findings = collect_listeners(fixture, allow_list=_allowlist())
    assert len(findings) == 1
    assert findings[0].severity == Severity.EMERGENCY
    assert findings[0].evidence["port"] == 22
    assert findings[0].evidence["process"] == "nc"


def test_new_loopback_listener_is_warning():
    findings = collect_listeners(NEW_LOCAL_LISTENER_FIXTURE, allow_list=_allowlist())
    warnings = [f for f in findings if f.severity == Severity.WARNING]
    assert len(warnings) == 1
    f = warnings[0]
    assert f.finding_type == "network.loopback_listener_unallowlisted"
    assert f.evidence["bind_address"] == "127.0.0.1"
    assert f.evidence["port"] == 9999


def test_loopback_address_helper_handles_rfc_loopback_and_malformed_input():
    assert is_loopback_address("127.0.0.53") is True
    assert is_loopback_address("::1") is True
    assert is_loopback_address("not-an-ip") is False


def test_loopback_address_helper_strips_scope_id_suffix():
    assert is_loopback_address("127.0.0.53%lo") is True


def test_loopback_process_identity_allows_dynamic_loopback_port():
    fixture = (
        'LISTEN 0      4096   127.0.0.1:39477      0.0.0.0:*  users:(("llama-server",pid=7,fd=1))\n'
    )
    findings = collect_listeners(fixture, allow_list=_allowlist())
    assert findings == []


def test_loopback_process_identity_allows_ipv6_loopback_port():
    fixture = (
        'LISTEN 0      4096   [::1]:47018        [::]:*  users:(("llama-server",pid=7,fd=1))\n'
    )
    findings = collect_listeners(fixture, allow_list=_allowlist())
    assert findings == []


def test_loopback_process_identity_does_not_allow_public_bind():
    fixture = (
        'LISTEN 0      4096   0.0.0.0:39477       0.0.0.0:*  users:(("llama-server",pid=7,fd=1))\n'
    )
    findings = collect_listeners(fixture, allow_list=_allowlist())
    assert len(findings) == 1
    assert findings[0].severity == Severity.EMERGENCY
    assert findings[0].evidence["bind_address"] == "0.0.0.0"


def test_allowlisted_public_listener_emits_no_finding():
    fixture = (
        'LISTEN 0      128    0.0.0.0:22           0.0.0.0:*  users:(("sshd",pid=900,fd=3))\n'
    )
    findings = collect_listeners(fixture, allow_list=_allowlist())
    assert findings == []


def test_malformed_row_yields_collector_warning_not_silence():
    findings = collect_listeners("this is not a valid ss line\n", allow_list=_allowlist())
    assert any(f.finding_type == "network.collector" for f in findings)


def test_finding_id_stable_across_calls():
    first = collect_listeners(PUBLIC_INTRUDER_FIXTURE, allow_list=_allowlist())
    second = collect_listeners(PUBLIC_INTRUDER_FIXTURE, allow_list=_allowlist())
    assert {f.id for f in first} == {f.id for f in second}


def test_all_expected_services_present_emits_no_finding():
    fixture = (
        'LISTEN 0      4096   127.0.0.53:53        0.0.0.0:*  users:(("systemd-resolved",pid=1,fd=1))\n'
        'LISTEN 0      4096   127.0.0.1:5001       0.0.0.0:*  users:(("python3.11",pid=1,fd=1))\n'
        'LISTEN 0      4096   127.0.0.1:8090       0.0.0.0:*  users:(("llama-server",pid=2,fd=2))\n'
    )
    services = ExpectedServices(loopback_ports=frozenset({53, 5001, 8090}))
    findings = collect_service_presence(fixture, expected=services)
    assert findings == []


def test_missing_expected_service_is_critical():
    fixture = (
        'LISTEN 0      4096   127.0.0.1:5001       0.0.0.0:*  users:(("python3.11",pid=1,fd=1))\n'
    )
    services = ExpectedServices(loopback_ports=frozenset({5001, 8090}))
    findings = collect_service_presence(fixture, expected=services)
    assert len(findings) == 1
    f = findings[0]
    assert f.severity == Severity.CRITICAL
    assert f.finding_type == "network.service_missing"
    assert f.evidence["port"] == 8090
    assert f.evidence["bind_address"] == "127.0.0.1"


def test_service_presence_unaffected_by_extra_listeners():
    fixture = (
        'LISTEN 0      4096   127.0.0.1:5001       0.0.0.0:*  users:(("python3.11",pid=1,fd=1))\n'
        'LISTEN 0      4096   127.0.0.1:8090       0.0.0.0:*  users:(("llama-server",pid=2,fd=2))\n'
        'LISTEN 0      128    127.0.0.1:9999       0.0.0.0:*  users:(("randomthing",pid=3,fd=3))\n'
    )
    services = ExpectedServices(loopback_ports=frozenset({5001, 8090}))
    findings = collect_service_presence(fixture, expected=services)
    assert findings == []


def test_network_allowlist_from_env_defaults_include_loopback_process_name():
    allowlist = NetworkAllowList.from_env({})
    assert "llama-server" in allowlist.loopback_process_names


def test_network_allowlist_from_env_override_loopback_process_names():
    allowlist = NetworkAllowList.from_env({
        "ARES_NET_LOOPBACK_PROCESS_ALLOWLIST": "llama-server,embeddings",
    })
    assert allowlist.loopback_process_names == frozenset({"llama-server", "embeddings"})


def test_network_allowlist_from_env_trims_blank_process_names():
    allowlist = NetworkAllowList.from_env({
        "ARES_NET_LOOPBACK_PROCESS_ALLOWLIST": " llama-server , , embeddings ,, ",
    })
    assert allowlist.loopback_process_names == frozenset({"llama-server", "embeddings"})


def test_expected_services_from_env_override_loopback_ports():
    services = ExpectedServices.from_env({"ARES_NET_EXPECTED_LOOPBACK": "5001, 8090, 53"})
    assert services.loopback_ports == frozenset({53, 5001, 8090})
