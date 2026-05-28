"""Fixture-driven tests for Ares hardware lane collectors."""

from __future__ import annotations

from soveryn.agents.ares.findings import Severity
from soveryn.agents.ares.lanes.hardware import (
    DiskSpaceThresholds,
    GpuThresholds,
    collect_cpu,
    collect_drives,
    collect_gpu,
    nvidia_smi_query_args,
)

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


L3_MCE_LOG = """
[Tue May 26 14:22:10 2026] mce: [Hardware Error]: CPU 0: Machine Check: 0 Bank 4: bea0000000000108
[Tue May 26 14:22:10 2026] mce: [Hardware Error]: TSC 0 ADDR 1ffff8100 MISC d012000100000000 SYND 4d000000 IPID 500b000000000
[Tue May 26 14:22:10 2026] mce: [Hardware Error]: PROCESSOR 2:a20f12 TIME 1779823330 SOCKET 0 APIC 0 microcode a20120e
[Tue May 26 14:22:10 2026] mce: [Hardware Error]: L3 cache data array error, corrected
"""

SMART_HEALTHY = """
SMART overall-health self-assessment test result: PASSED
ID# ATTRIBUTE_NAME          FLAG     VALUE WORST THRESH TYPE      UPDATED  WHEN_FAILED RAW_VALUE
  5 Reallocated_Sector_Ct   0x0033   100   100   010    Pre-fail  Always       -       0
"""

SMART_WARNING = """
SMART overall-health self-assessment test result: PASSED
ID# ATTRIBUTE_NAME          FLAG     VALUE WORST THRESH TYPE      UPDATED  WHEN_FAILED RAW_VALUE
  5 Reallocated_Sector_Ct   0x0033   100   100   010    Pre-fail  Always       -       12
"""

SMART_FAIL = """
SMART overall-health self-assessment test result: FAILED!
ID# ATTRIBUTE_NAME          FLAG     VALUE WORST THRESH TYPE      UPDATED  WHEN_FAILED RAW_VALUE
  5 Reallocated_Sector_Ct   0x0033   050   050   010    Pre-fail  Always       -       200
"""


def test_collect_cpu_edac_corrected_warning_and_uncorrected_critical():
    findings = collect_cpu(edac_counters={"ce_count": 3, "ue_count": 1}, mce_log="")

    assert [finding.finding_type for finding in findings] == ["cpu.edac", "cpu.edac"]
    assert [finding.severity for finding in findings] == [Severity.WARNING, Severity.CRITICAL]
    assert findings[0].evidence == {"counter": "ce_count", "count": 3}
    assert findings[1].evidence == {"counter": "ue_count", "count": 1}


def test_collect_cpu_l3_mce_corrected_class_is_warning():
    findings = collect_cpu(edac_counters={}, mce_log=L3_MCE_LOG)

    assert len(findings) == 1
    assert findings[0].finding_type == "cpu.mce"
    assert findings[0].severity is Severity.WARNING
    assert findings[0].evidence["class"] == "l3-cache"
    assert findings[0].evidence["corrected"] is True


def test_collect_cpu_uncorrected_mce_is_critical():
    log = "mce: [Hardware Error]: CPU 3: Machine Check Exception: uncorrected memory error"

    findings = collect_cpu(edac_counters={}, mce_log=log)

    assert findings[0].finding_type == "cpu.mce"
    assert findings[0].severity is Severity.CRITICAL
    assert findings[0].evidence["corrected"] is False


def test_collect_drives_smart_health_fail_is_critical():
    findings = collect_drives(smart_outputs={"/dev/nvme0n1": SMART_FAIL})

    assert len(findings) == 1
    assert findings[0].finding_type == "drive.smart"
    assert findings[0].severity is Severity.CRITICAL
    assert findings[0].evidence["device"] == "/dev/nvme0n1"
    assert findings[0].evidence["overall_health"] == "failed"


def test_collect_drives_reallocated_sectors_warning_and_healthy_info():
    findings = collect_drives(smart_outputs={
        "/dev/nvme0n1": SMART_WARNING,
        "/dev/nvme1n1": SMART_HEALTHY,
    })

    assert [finding.severity for finding in findings] == [Severity.WARNING, Severity.INFO]
    assert findings[0].finding_type == "drive.smart"
    assert findings[0].evidence["reallocated_sectors"] == 12
    assert findings[1].finding_type == "drive.smart"
    assert findings[1].evidence["overall_health"] == "passed"


def test_collect_drives_filesystem_space_thresholds():
    thresholds = DiskSpaceThresholds(warn_free_pct=15.0, critical_free_pct=5.0)
    findings = collect_drives(
        disk_usages={
            "/": (100, 87, 13),
            "/mnt/critical": (100, 97, 3),
            "/mnt/healthy": (100, 20, 80),
        },
        space_thresholds=thresholds,
    )

    assert [finding.severity for finding in findings] == [Severity.WARNING, Severity.CRITICAL]
    assert [finding.evidence["path"] for finding in findings] == ["/", "/mnt/critical"]


def test_collect_drives_missing_expected_mount_warning():
    proc_mounts = """
/dev/nvme0n1p2 / ext4 rw,relatime 0 0
/dev/sda1 /mnt/easystore ntfs3 rw,relatime 0 0
"""

    findings = collect_drives(proc_mounts=proc_mounts, expected_mounts=["/mnt/easystore", "/mnt/missing"])

    assert len(findings) == 1
    assert findings[0].finding_type == "drive.mount"
    assert findings[0].severity is Severity.WARNING
    assert findings[0].evidence == {"mount": "/mnt/missing", "reason": "missing"}
