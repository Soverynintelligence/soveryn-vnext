"""Tests for the system_probe read-only host-inventory tool.

Injected runner returns canned nvidia-smi/lspci/lscpu fixtures → asserts the
structured parse. Also asserts the security boundary: no user input ever
reaches a command (the category selects a hardcoded command set).
"""

import pytest

from soveryn.platform.system_probe import (
    ProbeError,
    ProbeResult,
    build_system_probe_tool,
    run_system_probe,
)
from soveryn.platform.tools.registry import ToolArgError, ToolRegistry


NVIDIA_SMI_FIXTURE = (
    "Quadro RTX 8000, 570.86.16, 49152 MiB, 00000000:41:00.0, 7.5\n"
    "NVIDIA RTX PRO 5000 Blackwell, 570.86.16, 49140 MiB, 00000000:C1:00.0, 10.0\n"
)

LSPCI_FIXTURE = (
    "01:00.0 VGA compatible controller: NVIDIA Corporation Device\n"
    "41:00.0 3D controller: NVIDIA Corporation TU102GL [Quadro RTX 8000]\n"
    "c1:00.0 Ethernet controller: Broadcom Inc. NetXtreme BCM57416 10G\n"
)

LSCPU_FIXTURE = (
    "Architecture:            x86_64\n"
    "Model name:              AMD EPYC 7763 64-Core Processor\n"
    "CPU(s):                  128\n"
)


class _RecordingRunner:
    """Injected runner that records every argv it is asked to run."""

    def __init__(self, responses):
        self._responses = responses
        self.calls: list[list[str]] = []

    def __call__(self, argv):
        self.calls.append(list(argv))
        # Dispatch on the command name (argv[0]).
        return self._responses.get(argv[0], "")


def test_gpu_probe_parses_nvidia_smi():
    runner = _RecordingRunner({"nvidia-smi": NVIDIA_SMI_FIXTURE})
    result = run_system_probe("gpu", runner=runner)
    assert isinstance(result, ProbeResult)
    assert result.category == "gpu"
    assert result.fields["gpu_count"] == "2"
    assert result.fields["gpu0.name"] == "Quadro RTX 8000"
    assert result.fields["gpu0.driver_version"] == "570.86.16"
    assert result.fields["gpu1.name"] == "NVIDIA RTX PRO 5000 Blackwell"
    assert NVIDIA_SMI_FIXTURE.strip() in result.raw
    assert result.probed_at  # stamped


def test_net_probe_filters_lspci_to_network_lines():
    runner = _RecordingRunner({"lspci": LSPCI_FIXTURE})
    result = run_system_probe("net", runner=runner)
    assert result.fields["net_count"] == "1"
    assert result.fields["net0.slot"] == "c1:00.0"
    assert "Broadcom" in result.fields["net0.desc"]


def test_cpu_probe_parses_lscpu():
    runner = _RecordingRunner({"lscpu": LSCPU_FIXTURE})
    result = run_system_probe("cpu", runner=runner)
    assert "AMD EPYC 7763 64-Core Processor" in result.fields["Model name"]


def test_board_probe_reads_dmi_files():
    def fake_dmi(path):
        return {
            "/sys/devices/virtual/dmi/id/board_vendor": "ASUSTeK COMPUTER INC.\n",
            "/sys/devices/virtual/dmi/id/board_name": "ROMED8-2T\n",
        }.get(path, "")

    result = run_system_probe("board", runner=lambda a: "", dmi_reader=fake_dmi)
    assert result.fields["board_vendor"].startswith("ASUSTeK")
    assert result.fields["board_name"] == "ROMED8-2T"


def test_all_category_runs_every_probe():
    runner = _RecordingRunner({
        "nvidia-smi": NVIDIA_SMI_FIXTURE,
        "lscpu": LSCPU_FIXTURE,
        "free": "Mem: 100G 50G",
        "lspci": LSPCI_FIXTURE,
    })
    result = run_system_probe("all", runner=runner, dmi_reader=lambda p: "")
    # Every allowlisted command ran, exactly once each.
    ran = [c[0] for c in runner.calls]
    assert ran == ["nvidia-smi", "lscpu", "free", "lspci"]


def test_unknown_category_raises():
    with pytest.raises(ProbeError):
        run_system_probe("rootkit", runner=lambda a: "")


def test_only_allowlisted_commands_run_no_user_input():
    """SECURITY BOUNDARY: the argv the runner sees is allowlist-constant.

    Whatever the caller passes as `category`, the runner only ever receives
    the hardcoded command sets — no caller token is interpolated anywhere.
    """
    runner = _RecordingRunner({
        "nvidia-smi": NVIDIA_SMI_FIXTURE, "lscpu": "", "free": "", "lspci": "",
    })
    run_system_probe("all", runner=runner, dmi_reader=lambda p: "")
    allowed_argv0 = {"nvidia-smi", "lscpu", "free", "lspci"}
    for argv in runner.calls:
        assert argv[0] in allowed_argv0
        # No shell metacharacters, no injected tokens — argv is constant.
        for token in argv:
            assert ";" not in token and "&&" not in token and "|" not in token


def test_tool_handler_returns_serialisable_dict():
    registry = ToolRegistry(active_agents=("vett",), audit_hook=None)
    runner = _RecordingRunner({"nvidia-smi": NVIDIA_SMI_FIXTURE, "lscpu": "", "free": "", "lspci": ""})
    registry.register(build_system_probe_tool(owner_agent="vett", runner=runner))
    out = registry.invoke("vett", "system_probe", {"category": "gpu"})
    assert out["category"] == "gpu"
    assert out["fields"]["gpu_count"] == "2"
    assert isinstance(out["raw"], str)


def test_tool_handler_rejects_bad_category():
    registry = ToolRegistry(active_agents=("vett",), audit_hook=None)
    registry.register(build_system_probe_tool(owner_agent="vett", runner=lambda a: ""))
    # jsonschema enum rejects at the registry boundary.
    with pytest.raises(ToolArgError):
        registry.invoke("vett", "system_probe", {"category": "; rm -rf /"})
