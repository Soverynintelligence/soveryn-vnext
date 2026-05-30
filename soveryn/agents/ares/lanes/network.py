"""Network collectors for Ares host sentinel."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from soveryn.agents.ares.findings import AresFinding, Severity


LOOPBACK_BIND_ADDRESSES = frozenset({"127.0.0.1", "::1"})


@dataclass(frozen=True)
class NetworkAllowList:
    """Ports allowed to listen, split by bind class."""

    loopback_ports: frozenset[int] = field(default_factory=frozenset)
    public_ports: frozenset[tuple[int, str]] = field(default_factory=frozenset)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "NetworkAllowList":
        env = env or os.environ
        return cls(
            loopback_ports=frozenset(_parse_port_list(env.get(
                "ARES_NET_LOOPBACK_ALLOWLIST",
                "5001,8090,8087,47017,39477",
            ))),
            public_ports=frozenset(_parse_public_allowlist(env.get(
                "ARES_NET_PUBLIC_ALLOWLIST",
                "22:sshd",
            ))),
        )


@dataclass(frozen=True)
class ExpectedServices:
    """Listeners that must be present; absence means service hard-down."""

    loopback_ports: frozenset[int] = field(default_factory=frozenset)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "ExpectedServices":
        env = env or os.environ
        return cls(loopback_ports=frozenset(_parse_port_list(env.get(
            "ARES_NET_EXPECTED_LOOPBACK",
            "5001,8090",
        ))))


_LISTEN_RE = re.compile(
    r"^LISTEN\s+\S+\s+\S+\s+(?P<local>\S+)\s+\S+"
    r"(?:\s+users:\(\(\"(?P<proc>[^\"]+)\",pid=(?P<pid>\d+)[^)]*\)\))?"
)


def collect_listeners(
    ss_output: str,
    *,
    allow_list: NetworkAllowList,
) -> list[AresFinding]:
    """Classify captured `ss -H -tlnp` listener rows."""

    findings: list[AresFinding] = []
    for raw_line in ss_output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _LISTEN_RE.match(line)
        if match is None:
            findings.append(AresFinding(
                "network.collector",
                Severity.WARNING,
                {"line": line, "reason": "unparseable-ss-row"},
                key=line,
            ))
            continue
        try:
            bind_address, port = _split_local(match.group("local"))
        except ValueError as exc:
            findings.append(AresFinding(
                "network.collector",
                Severity.WARNING,
                {"line": line, "reason": str(exc)},
                key=line,
            ))
            continue
        process = match.group("proc") or ""
        finding = _classify(bind_address, port, process, allow_list)
        if finding is not None:
            findings.append(finding)
    return findings


def collect_service_presence(
    ss_output: str,
    *,
    expected: ExpectedServices,
) -> list[AresFinding]:
    """Detect expected loopback listeners that are missing from captured ss output."""

    present_loopback: set[int] = set()
    for raw_line in ss_output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _LISTEN_RE.match(line)
        if match is None:
            continue
        try:
            bind_address, port = _split_local(match.group("local"))
        except ValueError:
            continue
        if bind_address in LOOPBACK_BIND_ADDRESSES:
            present_loopback.add(port)

    findings: list[AresFinding] = []
    for missing in sorted(expected.loopback_ports - present_loopback):
        findings.append(AresFinding(
            "network.service_missing",
            Severity.CRITICAL,
            {"bind_address": "127.0.0.1", "port": missing},
            key=f"127.0.0.1:{missing}",
        ))
    return findings


def _split_local(local: str) -> tuple[str, int]:
    if local.startswith("["):
        host, separator, port_text = local[1:].partition("]:")
        if not separator or not port_text:
            raise ValueError(f"bad-ipv6-local-addr: {local}")
        return host, int(port_text)
    host, separator, port_text = local.rpartition(":")
    if not separator or not port_text:
        raise ValueError(f"bad-local-addr: {local}")
    return host, int(port_text)


def _classify(
    bind_address: str,
    port: int,
    process: str,
    allow_list: NetworkAllowList,
) -> AresFinding | None:
    if bind_address in LOOPBACK_BIND_ADDRESSES:
        if port in allow_list.loopback_ports:
            return None
        return AresFinding(
            "network.loopback_listener_unallowlisted",
            Severity.WARNING,
            {"bind_address": bind_address, "port": port, "process": process},
            key=f"{bind_address}:{port}:{process}",
        )
    if (port, process) in allow_list.public_ports:
        return None
    return AresFinding(
        "network.public_listener_unallowlisted",
        Severity.EMERGENCY,
        {"bind_address": bind_address, "port": port, "process": process},
        key=f"{bind_address}:{port}:{process}",
    )


def _parse_port_list(value: str) -> list[int]:
    return [int(part) for part in value.split(",") if part.strip().isdigit()]


def _parse_public_allowlist(value: str) -> list[tuple[int, str]]:
    entries: list[tuple[int, str]] = []
    for raw_part in value.split(","):
        part = raw_part.strip()
        if not part:
            continue
        port_text, separator, process = part.partition(":")
        if not separator or not port_text.isdigit() or not process.strip():
            continue
        entries.append((int(port_text), process.strip()))
    return entries
