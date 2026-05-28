"""Fixture-driven tests for Ares hardware lane collectors."""

from __future__ import annotations

from soveryn.agents.ares.findings import Severity
from soveryn.agents.ares.lanes.hardware import GpuThresholds, collect_gpu, nvidia_smi_query_args

HEALTHY_NVIDIA_SMI = """
0, Quadro RTX 8000, 39, 36445, 49152, [N/A], [N/A]
1, NVIDIA RTX PRO 5000 Blackwell, 59, 37330, 48935, [N/A], [N/A]
2, Quadro RTX 8000, 42, 32591, 49152, [N/A], [N/A]
"""

HOT_NVIDIA_SMI = """
0, Quadro RTX 8000, 80, 12000, 49152, 0, 0
1, NVIDIA RTX PRO 5000 Blackwell, 89, 16000, 48935, 0, 0
2, Quadro RTX 8000, 90, 20000, 49152, 0, 0
"""

ECC_NVIDIA_SMI = """
0, Quadro RTX 8000, 42, 12000, 49152, 1, 0
1, NVIDIA RTX PRO 5000 Blackwell, 45, 16000, 48935, 0, 2
"""


def test_nvidia_smi_query_args_match_parser_columns():
    assert nvidia_smi_query_args() == [
        "nvidia-smi",
        "--query-gpu=index,name,temperature.gpu,memory.used,memory.total,"
        "ecc.errors.uncorrected.volatile.total,ecc.errors.uncorrected.aggregate.total",
        "--format=csv,noheader,nounits",
    ]


def test_collect_gpu_healthy_fixture_emits_info_trend_findings():
    findings = collect_gpu(HEALTHY_NVIDIA_SMI)

    assert [finding.severity for finding in findings] == [Severity.INFO, Severity.INFO, Severity.INFO]
    assert [finding.finding_type for finding in findings] == [
        "gpu.status",
        "gpu.status",
        "gpu.status",
    ]
    assert findings[0].id == "gpu.status:gpu0"
    assert findings[0].evidence == {
        "index": 0,
        "name": "Quadro RTX 8000",
        "temperature_c": 39,
        "memory_used_mb": 36445,
        "memory_total_mb": 49152,
        "ecc_uncorrected_volatile": None,
        "ecc_uncorrected_aggregate": None,
    }


def test_collect_gpu_warning_and_critical_temperature_thresholds():
    thresholds = GpuThresholds(warn_temp_c=80, critical_temp_c=90)
    findings = collect_gpu(HOT_NVIDIA_SMI, thresholds=thresholds)

    assert [finding.severity for finding in findings] == [
        Severity.WARNING,
        Severity.WARNING,
        Severity.CRITICAL,
    ]
    assert findings[0].finding_type == "gpu.temperature"
    assert findings[0].evidence["temperature_c"] == 80
    assert findings[2].finding_type == "gpu.temperature"
    assert findings[2].evidence["temperature_c"] == 90


def test_collect_gpu_uncorrected_ecc_errors_are_critical():
    findings = collect_gpu(ECC_NVIDIA_SMI)

    assert [finding.severity for finding in findings] == [Severity.CRITICAL, Severity.CRITICAL]
    assert [finding.finding_type for finding in findings] == ["gpu.ecc", "gpu.ecc"]
    assert findings[0].evidence["ecc_uncorrected_volatile"] == 1
    assert findings[1].evidence["ecc_uncorrected_aggregate"] == 2


def test_collect_gpu_thresholds_are_config_driven():
    fixture = "0, Quadro RTX 8000, 72, 1000, 49152, 0, 0"

    default_findings = collect_gpu(fixture)
    tuned_findings = collect_gpu(fixture, thresholds=GpuThresholds(warn_temp_c=70, critical_temp_c=75))

    assert default_findings[0].severity is Severity.INFO
    assert tuned_findings[0].severity is Severity.WARNING


def test_collect_gpu_skips_blank_lines_and_marks_malformed_rows_warning():
    findings = collect_gpu("\nnot,enough,fields\n")

    assert len(findings) == 1
    assert findings[0].finding_type == "gpu.collector"
    assert findings[0].severity is Severity.WARNING
    assert findings[0].evidence == {"line": "not,enough,fields", "reason": "malformed-row"}


def test_gpu_thresholds_can_be_loaded_from_env():
    thresholds = GpuThresholds.from_env({
        "ARES_GPU_WARN_TEMP_C": "70",
        "ARES_GPU_CRITICAL_TEMP_C": "85",
    })

    assert thresholds == GpuThresholds(warn_temp_c=70, critical_temp_c=85)
