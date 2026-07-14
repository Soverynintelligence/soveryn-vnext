"""Tests for soveryn/app/services/spark_stats.py."""

from soveryn.app.services.spark_stats import (
    _parse_probe, _parse_prometheus, SparkContainer,
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
