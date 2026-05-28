"""Hardware collectors for Ares host sentinel."""

from __future__ import annotations

import os
import subprocess
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
