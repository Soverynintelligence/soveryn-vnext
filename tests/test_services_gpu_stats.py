"""Tests for soveryn/app/services/gpu_stats.py."""

from unittest.mock import patch
import subprocess

from soveryn.app.services.gpu_stats import (
    get_gpu_stats, _parse_nvidia_smi, GpuStat, GpuStatsResult,
)


def test_parse_nvidia_smi_three_gpus():
    raw = (
        "0, 45, 80, 55.0, 49152\n"
        "1, 65, 88, 70.5, 49152\n"
        "2, 32, 75, 40.2, 49152\n"
    )
    result = _parse_nvidia_smi(raw)
    assert len(result) == 3
    assert result[0] == GpuStat(index=0, util_pct=45, temp_c=80, mem_used_mib=55.0, mem_total_mib=49152)
    assert result[2].index == 2


def test_parse_nvidia_smi_handles_blank_lines():
    raw = "0, 10, 50, 5.0, 49152\n\n"
    result = _parse_nvidia_smi(raw)
    assert len(result) == 1


def test_parse_nvidia_smi_empty():
    assert _parse_nvidia_smi("") == []


def test_get_gpu_stats_with_smi_available():
    fake_output = "0, 50, 70, 12.0, 49152\n1, 25, 60, 8.0, 49152\n"
    fake = subprocess.CompletedProcess(args=[], returncode=0, stdout=fake_output, stderr="")
    with patch("subprocess.run", return_value=fake):
        r = get_gpu_stats(_force_refresh=True)
    assert r.available is True
    assert len(r.gpus) == 2
    assert r.gpus[0].util_pct == 50


def test_get_gpu_stats_falls_back_when_smi_missing():
    with patch("subprocess.run", side_effect=FileNotFoundError("nvidia-smi")):
        r = get_gpu_stats(_force_refresh=True)
    assert r.available is False
    assert r.gpus == []
    assert "not available" in r.message.lower()


def test_get_gpu_stats_falls_back_on_nonzero_exit():
    fake = subprocess.CompletedProcess(args=[], returncode=9, stdout="", stderr="error")
    with patch("subprocess.run", return_value=fake):
        r = get_gpu_stats(_force_refresh=True)
    assert r.available is False
    assert "error" in r.message.lower() or "exit" in r.message.lower()


def test_get_gpu_stats_caches_within_window():
    """Second call within 5s reuses cached result (subprocess.run only invoked once)."""
    fake = subprocess.CompletedProcess(args=[], returncode=0,
        stdout="0, 1, 1, 1.0, 1\n", stderr="")
    with patch("subprocess.run", return_value=fake) as mock_run:
        get_gpu_stats(_force_refresh=True)
        get_gpu_stats()  # cached
        get_gpu_stats()  # cached
    assert mock_run.call_count == 1
