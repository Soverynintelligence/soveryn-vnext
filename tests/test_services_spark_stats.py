"""Tests for soveryn/app/services/spark_stats.py."""

import subprocess
import urllib.error
from unittest.mock import patch

from soveryn.app.services import spark_stats
from soveryn.app.services.spark_stats import (
    _parse_probe, _parse_prometheus, SparkContainer, get_spark_stats,
)

PROBE_OK = """45, 52
---
Mem:  129922760704 52613349376 17179869184 0 60129542144 74000000000
---
nemotron-spark|running
compare|running
"""

# GB10 reports [N/A] for anything memory-related, and may for util/temp too.
PROBE_NA = """[N/A], [N/A]
---
Mem:  129922760704 52613349376 17179869184 0 60129542144 74000000000
---
nemotron-spark|running
"""


def test_parse_probe_reads_gpu_and_unified_memory():
    host, containers = _parse_probe(PROBE_OK)
    assert host.gpu_util_pct == 45
    assert host.gpu_temp_c == 52
    # memory comes from `free -b`, NOT nvidia-smi
    assert host.mem_total_bytes == 129922760704
    assert host.mem_used_bytes == 52613349376
    assert containers == [
        SparkContainer(name="nemotron-spark", state="running"),
        SparkContainer(name="compare", state="running"),
    ]


def test_parse_probe_na_gpu_fields_degrade_to_none_not_garbage():
    """GB10's nvidia-smi returns [N/A]. That must become None, never 0 or a crash."""
    host, containers = _parse_probe(PROBE_NA)
    assert host.gpu_util_pct is None
    assert host.gpu_temp_c is None
    # memory still works, because it comes from free(1)
    assert host.mem_total_bytes == 129922760704
    assert len(containers) == 1


def test_parse_probe_empty_does_not_raise():
    host, containers = _parse_probe("")
    assert host.gpu_util_pct is None
    assert host.mem_total_bytes is None
    assert containers == []


def test_parse_prometheus_extracts_vllm_gauges():
    raw = (
        '# TYPE vllm:num_requests_running gauge\n'
        'vllm:num_requests_running{engine="0",model_name="nemotron"} 3.0\n'
        'vllm:num_requests_waiting{engine="0",model_name="nemotron"} 1.0\n'
        'vllm:kv_cache_usage_perc{engine="0",model_name="nemotron"} 0.42\n'
    )
    m = _parse_prometheus(raw)
    assert m["vllm:num_requests_running"] == 3.0
    assert m["vllm:num_requests_waiting"] == 1.0
    assert m["vllm:kv_cache_usage_perc"] == 0.42


def test_parse_prometheus_ignores_comments_and_junk():
    assert _parse_prometheus("# TYPE foo gauge\n\ngarbage line\n") == {}


def test_parse_prometheus_extracts_unbraced_lines():
    """Test lines without label braces, e.g., 'vllm:foo 1.0'."""
    raw = (
        'vllm:foo 1.0\n'
        'vllm:bar 2.5\n'
    )
    m = _parse_prometheus(raw)
    assert m["vllm:foo"] == 1.0
    assert m["vllm:bar"] == 2.5


def _ssh_ok(stdout=PROBE_OK):
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


def _ssh_fail():
    return subprocess.CompletedProcess(args=[], returncode=255, stdout="",
                                       stderr="ssh: connect ... No route to host")


METRICS = (
    'vllm:num_requests_running{model_name="nemotron"} 2.0\n'
    'vllm:num_requests_waiting{model_name="nemotron"} 0.0\n'
    'vllm:kv_cache_usage_perc{model_name="nemotron"} 0.25\n'
)


def _fake_http(url, timeout=0):
    """Stand-in for urllib.request.urlopen — supports `with ... as r: r.read()`."""
    class _R:
        def __enter__(self_inner):
            return self_inner
        def __exit__(self_inner, *a):
            return False
        def read(self_inner):
            if "/v1/models" in url:
                return b'{"data":[{"id":"nemotron"}]}'
            return METRICS.encode()
    return _R()


def test_fabric_path_is_preferred_and_reported():
    spark_stats._cache = None
    with patch("subprocess.run", return_value=_ssh_ok()) as run, \
         patch("urllib.request.urlopen", side_effect=_fake_http):
        r = get_spark_stats(_force_refresh=True)
    assert r.available is True
    assert r.path == "fabric"
    # the fabric address must be the one it tried first
    assert spark_stats.SPARK_FABRIC_HOST in " ".join(run.call_args_list[0][0][0])
    assert r.host.gpu_util_pct == 45
    assert r.vllm.up is True
    assert r.vllm.model == "nemotron"
    assert r.vllm.kv_cache_pct == 0.25


def test_wifi_fallback_is_reported_as_degraded():
    """THE POINT OF THIS FEATURE. Fabric down + WiFi up must NOT look healthy."""
    spark_stats._cache = None
    with patch("subprocess.run", side_effect=[_ssh_fail(), _ssh_ok()]), \
         patch("urllib.request.urlopen", side_effect=_fake_http):
        r = get_spark_stats(_force_refresh=True)
    assert r.available is True
    assert r.path == "wifi"          # <-- amber in the UI, not green


def test_both_paths_down_degrades_cleanly():
    spark_stats._cache = None
    with patch("subprocess.run", side_effect=[_ssh_fail(), _ssh_fail()]):
        r = get_spark_stats(_force_refresh=True)
    assert r.available is False
    assert r.path is None
    assert r.host is None
    assert r.containers == []
    assert r.message


def test_box_up_but_vllm_dead_still_reports_the_box():
    spark_stats._cache = None
    with patch("subprocess.run", return_value=_ssh_ok()), \
         patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
        r = get_spark_stats(_force_refresh=True)
    assert r.available is True
    assert r.host.gpu_util_pct == 45
    assert r.vllm.up is False


def test_ssh_missing_binary_degrades_cleanly():
    """No ssh on PATH must not escape get_spark_stats()."""
    spark_stats._cache = None
    with patch("subprocess.run", side_effect=FileNotFoundError("ssh")):
        r = get_spark_stats(_force_refresh=True)
    assert r.available is False
    assert r.path is None


def test_ssh_timeout_degrades_cleanly():
    spark_stats._cache = None
    with patch("subprocess.run",
               side_effect=subprocess.TimeoutExpired(cmd="ssh", timeout=8.0)):
        r = get_spark_stats(_force_refresh=True)
    assert r.available is False
    assert r.path is None


def test_ssh_unexpected_exception_degrades_cleanly():
    """A UnicodeDecodeError from text=True decoding stray remote bytes (or a
    PermissionError on an unexecutable ssh binary) must still degrade to
    'unreachable' rather than 500ing the dashboard route."""
    spark_stats._cache = None
    unicode_err = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
    with patch("subprocess.run", side_effect=unicode_err):
        r = get_spark_stats(_force_refresh=True)
    assert r.available is False
    assert r.path is None

    spark_stats._cache = None
    with patch("subprocess.run", side_effect=PermissionError("ssh not executable")):
        r = get_spark_stats(_force_refresh=True)
    assert r.available is False
    assert r.path is None


def test_caches_within_window():
    spark_stats._cache = None
    with patch("subprocess.run", return_value=_ssh_ok()) as run, \
         patch("urllib.request.urlopen", side_effect=_fake_http):
        get_spark_stats(_force_refresh=True)
        get_spark_stats()
        get_spark_stats()
    assert run.call_count == 1
