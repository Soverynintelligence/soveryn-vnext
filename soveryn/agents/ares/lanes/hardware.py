"""Hardware collectors for Ares host sentinel."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from dataclasses import dataclass

from soveryn.agents.ares.findings import AresFinding, Severity


@dataclass(frozen=True)
class GpuThresholds:
    warn_temp_c: int = 80
    critical_temp_c: int = 90

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "GpuThresholds":
        env = env or os.environ
        return cls(
            warn_temp_c=int(env.get("ARES_GPU_WARN_TEMP_C", "80")),
            critical_temp_c=int(env.get("ARES_GPU_CRITICAL_TEMP_C", "90")),
        )


@dataclass(frozen=True)
class DiskSpaceThresholds:
    warn_free_pct: float = 15.0
    critical_free_pct: float = 5.0

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "DiskSpaceThresholds":
        env = env or os.environ
        return cls(
            warn_free_pct=float(env.get("ARES_DISK_WARN_FREE_PCT", "15")),
            critical_free_pct=float(env.get("ARES_DISK_CRITICAL_FREE_PCT", "5")),
        )


def nvidia_smi_query_args() -> list[str]:
    return [
        "nvidia-smi",
        "--query-gpu=index,name,temperature.gpu,memory.used,memory.total,"
        "ecc.errors.uncorrected.volatile.total,ecc.errors.uncorrected.aggregate.total",
        "--format=csv,noheader,nounits",
    ]


def collect_gpu(nvidia_smi_output: str, *, thresholds: GpuThresholds | None = None) -> list[AresFinding]:
    thresholds = thresholds or GpuThresholds.from_env()
    findings: list[AresFinding] = []
    for raw_line in nvidia_smi_output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        fields = [field.strip() for field in line.split(",")]
        if len(fields) != 7:
            findings.append(AresFinding(
                "gpu.collector",
                Severity.WARNING,
                {"line": line, "reason": "malformed-row"},
                key=line,
            ))
            continue
        try:
            reading = _parse_gpu_fields(fields)
        except ValueError as exc:
            findings.append(AresFinding(
                "gpu.collector",
                Severity.WARNING,
                {"line": line, "reason": str(exc)},
                key=line,
            ))
            continue
        findings.append(_finding_for_reading(reading, thresholds=thresholds))
    return findings


def collect_gpu_live(timeout_seconds: float = 5.0) -> list[AresFinding]:
    try:
        result = subprocess.run(
            nvidia_smi_query_args(),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return [AresFinding(
            "gpu.collector",
            Severity.WARNING,
            {"reason": "nvidia-smi-timeout", "timeout_seconds": timeout_seconds},
            key="nvidia-smi",
        )]
    except OSError as exc:
        return [AresFinding(
            "gpu.collector",
            Severity.WARNING,
            {"reason": "nvidia-smi-error", "error": str(exc)},
            key="nvidia-smi",
        )]
    if result.returncode != 0:
        return [AresFinding(
            "gpu.collector",
            Severity.WARNING,
            {"reason": "nvidia-smi-failed", "returncode": result.returncode, "stderr": result.stderr.strip()},
            key="nvidia-smi",
        )]
    return collect_gpu(result.stdout)


def _parse_gpu_fields(fields: list[str]) -> dict:
    return {
        "index": _parse_int(fields[0], "index"),
        "name": fields[1],
        "temperature_c": _parse_int(fields[2], "temperature"),
        "memory_used_mb": _parse_int(fields[3], "memory_used"),
        "memory_total_mb": _parse_int(fields[4], "memory_total"),
        "ecc_uncorrected_volatile": _parse_optional_int(fields[5], "ecc_volatile"),
        "ecc_uncorrected_aggregate": _parse_optional_int(fields[6], "ecc_aggregate"),
    }


def _finding_for_reading(reading: dict, *, thresholds: GpuThresholds) -> AresFinding:
    key = f"gpu{reading['index']}"
    ecc_volatile = reading["ecc_uncorrected_volatile"] or 0
    ecc_aggregate = reading["ecc_uncorrected_aggregate"] or 0
    if ecc_volatile > 0 or ecc_aggregate > 0:
        return AresFinding("gpu.ecc", Severity.CRITICAL, reading, key=key)
    temp = reading["temperature_c"]
    if temp >= thresholds.critical_temp_c:
        return AresFinding("gpu.temperature", Severity.CRITICAL, reading, key=key)
    if temp >= thresholds.warn_temp_c:
        return AresFinding("gpu.temperature", Severity.WARNING, reading, key=key)
    return AresFinding("gpu.status", Severity.INFO, reading, key=key)


def _parse_int(value: str, field_name: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"invalid-{field_name}") from exc


def _parse_optional_int(value: str, field_name: str) -> int | None:
    if value in {"[N/A]", "N/A", ""}:
        return None
    return _parse_int(value, field_name)


def collect_cpu(
    *,
    edac_counters: dict[str, int] | None = None,
    mce_log: str = "",
) -> list[AresFinding]:
    findings: list[AresFinding] = []
    for counter, count in sorted((edac_counters or {}).items()):
        if count <= 0:
            continue
        normalized = counter.lower()
        if normalized.startswith("ue") or "uncorrected" in normalized:
            findings.append(AresFinding(
                "cpu.edac",
                Severity.CRITICAL,
                {"counter": counter, "count": count},
                key=counter,
            ))
        elif normalized.startswith("ce") or "corrected" in normalized:
            findings.append(AresFinding(
                "cpu.edac",
                Severity.WARNING,
                {"counter": counter, "count": count},
                key=counter,
            ))
    for idx, line in enumerate(_hardware_error_lines(mce_log)):
        lowered = line.lower()
        corrected = "uncorrected" not in lowered and "corrected" in lowered
        finding_class = "l3-cache" if "l3" in lowered else "mce"
        findings.append(AresFinding(
            "cpu.mce",
            Severity.WARNING if corrected else Severity.CRITICAL,
            {"line": line, "class": finding_class, "corrected": corrected},
            key=f"mce{idx}:{finding_class}",
        ))
    return findings


def collect_drives(
    *,
    smart_outputs: dict[str, str] | None = None,
    disk_usages: dict[str, tuple[int, int, int]] | None = None,
    proc_mounts: str = "",
    expected_mounts: list[str] | tuple[str, ...] | None = None,
    space_thresholds: DiskSpaceThresholds | None = None,
) -> list[AresFinding]:
    findings: list[AresFinding] = []
    for device, output in sorted((smart_outputs or {}).items()):
        findings.append(_smart_finding(device, output))
    thresholds = space_thresholds or DiskSpaceThresholds.from_env()
    for path, usage in sorted((disk_usages or {}).items()):
        total, used, free = usage
        if total <= 0:
            continue
        free_pct = (free / total) * 100.0
        evidence = {"path": path, "total": total, "used": used, "free": free, "free_pct": free_pct}
        if free_pct < thresholds.critical_free_pct:
            findings.append(AresFinding("drive.space", Severity.CRITICAL, evidence, key=path))
        elif free_pct < thresholds.warn_free_pct:
            findings.append(AresFinding("drive.space", Severity.WARNING, evidence, key=path))
    mounted = _mount_points(proc_mounts)
    for mount in expected_mounts or ():
        if mount not in mounted:
            findings.append(AresFinding(
                "drive.mount",
                Severity.WARNING,
                {"mount": mount, "reason": "missing"},
                key=mount,
            ))
    return findings


def _hardware_error_lines(log: str) -> list[str]:
    return [
        line.strip() for line in log.splitlines()
        if line.strip() and ("hardware error" in line.lower() or "mce" in line.lower())
        and ("corrected" in line.lower() or "uncorrected" in line.lower())
    ]


def _smart_finding(device: str, output: str) -> AresFinding:
    health = _smart_health(output)
    reallocated = _smart_reallocated_sectors(output)
    evidence = {
        "device": device,
        "overall_health": health,
        "reallocated_sectors": reallocated,
    }
    if health == "failed":
        return AresFinding("drive.smart", Severity.CRITICAL, evidence, key=device)
    if reallocated > 0:
        return AresFinding("drive.smart", Severity.WARNING, evidence, key=device)
    return AresFinding("drive.smart", Severity.INFO, evidence, key=device)


def _smart_health(output: str) -> str:
    for line in output.splitlines():
        lowered = line.lower()
        if "overall-health" not in lowered and "self-assessment" not in lowered:
            continue
        if "fail" in lowered:
            return "failed"
        if "pass" in lowered:
            return "passed"
    return "passed"


def _smart_reallocated_sectors(output: str) -> int:
    for line in output.splitlines():
        if "Reallocated_Sector_Ct" not in line:
            continue
        parts = line.split()
        if not parts:
            continue
        try:
            return int(parts[-1])
        except ValueError:
            return 0
    return 0


def _mount_points(proc_mounts: str) -> set[str]:
    points: set[str] = set()
    for line in proc_mounts.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            points.add(parts[1])
    return points


def collect_cpu_live(
    *,
    edac_root: Path = Path("/sys/devices/system/edac"),
    dmesg_timeout_seconds: float = 5.0,
) -> list[AresFinding]:
    counters = _read_edac_counters(edac_root)
    mce_log = _read_dmesg(timeout_seconds=dmesg_timeout_seconds)
    return collect_cpu(edac_counters=counters, mce_log=mce_log)


def collect_drives_live(
    *,
    devices: list[str] | tuple[str, ...] = (),
    paths: list[str] | tuple[str, ...] = ("/",),
    expected_mounts: list[str] | tuple[str, ...] = (),
    smartctl_timeout_seconds: float = 10.0,
) -> list[AresFinding]:
    smart_outputs: dict[str, str] = {}
    for device in devices:
        smart_outputs[device] = _read_smartctl(device, timeout_seconds=smartctl_timeout_seconds)
    disk_usages = {path: _disk_usage_tuple(path) for path in paths}
    proc_mounts = _read_text(Path("/proc/mounts"))
    return collect_drives(
        smart_outputs=smart_outputs,
        disk_usages=disk_usages,
        proc_mounts=proc_mounts,
        expected_mounts=expected_mounts,
    )


def _read_edac_counters(edac_root: Path) -> dict[str, int]:
    counters: dict[str, int] = {}
    if not edac_root.exists():
        return counters
    for path in edac_root.rglob("*_count"):
        try:
            value = int(path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            continue
        counters[path.name] = counters.get(path.name, 0) + value
    return counters


def _read_dmesg(*, timeout_seconds: float) -> str:
    try:
        result = subprocess.run(
            ["dmesg"],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout if result.returncode == 0 else ""


def _read_smartctl(device: str, *, timeout_seconds: float) -> str:
    try:
        result = subprocess.run(
            ["smartctl", "-H", "-A", device],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout if result.returncode in {0, 2, 4, 8, 16, 32, 64} else ""


def _disk_usage_tuple(path: str) -> tuple[int, int, int]:
    usage = shutil.disk_usage(path)
    return usage.total, usage.used, usage.free


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""
