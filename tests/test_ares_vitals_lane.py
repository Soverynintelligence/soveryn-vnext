from soveryn.agents.ares.findings import Severity
from soveryn.agents.ares.lanes import vitals

HER = vitals.HER_GPU_UUID
OTHER = "GPU-0000other0000"


def _by_type(findings):
    return {f.finding_type: f for f in findings}


def test_her_card_low_headroom_is_emergency():
    # her card: total 48935, used 47500 → free 1435 < 2048
    out = vitals.collect_gpu_headroom([(HER, 47500, 48935)])
    assert len(out) == 1
    assert out[0].finding_type == "gpu.headroom"
    assert out[0].severity == Severity.EMERGENCY
    assert out[0].evidence["free_mb"] == 1435
    assert out[0].key == HER


def test_her_card_early_warn_headroom_is_warning():
    # free 2800 → between 2048 and 3072 → WARNING
    out = vitals.collect_gpu_headroom([(HER, 46135, 48935)])
    assert out[0].severity == Severity.WARNING


def test_her_card_healthy_headroom_emits_nothing():
    # free 5800 → healthy → no finding (recovery handled by tracker clear)
    assert vitals.collect_gpu_headroom([(HER, 43135, 48935)]) == []


def test_other_card_low_headroom_is_critical():
    out = vitals.collect_gpu_headroom([(OTHER, 48500, 49152)])  # free 652 < 1024
    assert out[0].severity == Severity.CRITICAL


def test_foreign_proc_non_comfyui_on_her_card_is_critical():
    apps = [(HER, "999", "/home/jon-deoliveira/miniconda3/envs/f5tts/bin/python")]
    out = vitals.collect_foreign_procs(apps)
    assert out[0].finding_type == "gpu.foreign_proc"
    assert out[0].severity == Severity.CRITICAL
    assert out[0].evidence["evictable_comfyui"] is False


def test_comfyui_on_her_card_is_warning_and_evictable():
    apps = [(HER, "999", "/home/jon-deoliveira/miniconda3/envs/comfyui/bin/python")]
    out = vitals.collect_foreign_procs(apps)
    assert out[0].severity == Severity.WARNING
    assert out[0].evidence["evictable_comfyui"] is True


def test_her_llama_server_and_other_card_procs_are_ignored():
    apps = [
        (HER, "100", "/home/jon-deoliveira/llama.cpp_head/build/bin/llama-server"),  # hers
        (OTHER, "200", "/home/jon-deoliveira/miniconda3/envs/f5tts/bin/python"),      # not her card
    ]
    assert vitals.collect_foreign_procs(apps) == []


def test_delegation_stuck_fires_past_threshold():
    tasks = [("t1", "executing", 1000.0)]
    out = vitals.collect_delegation_stuck(tasks, now=1400.0)  # age 400 > 360
    assert out[0].finding_type == "delegation.stuck"
    assert out[0].severity == Severity.WARNING
    assert out[0].key == "t1"


def test_delegation_recent_or_terminal_is_ignored():
    tasks = [
        ("t1", "executing", 1300.0),  # age 100 < 360
        ("t2", "failed", 1.0),         # terminal
    ]
    assert vitals.collect_delegation_stuck(tasks, now=1400.0) == []


from soveryn.agents.ares import daemon as ares_daemon


def test_parse_gpu_headroom_rows_parses_csv():
    csv = "GPU-abc, 47500, 48935\nGPU-def, 100, 49152\n"
    assert vitals._parse_gpu_headroom_rows(csv) == [("GPU-abc", 47500, 48935), ("GPU-def", 100, 49152)]


def test_parse_compute_apps_parses_csv():
    csv = "GPU-abc, 999, /x/envs/comfyui/bin/python\n"
    assert vitals._parse_compute_apps(csv) == [("GPU-abc", "999", "/x/envs/comfyui/bin/python")]


def test_collect_vitals_live_is_zero_arg_and_safe(monkeypatch):
    # Force every underlying reader to raise; the lane must swallow and return [].
    monkeypatch.setattr(vitals, "_read_gpu_headroom_rows", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(vitals, "_read_compute_apps", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(vitals, "_read_executing_tasks", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert vitals.collect_vitals_live() == []


def test_vitals_lane_is_registered_in_default_collectors():
    collectors = ares_daemon._default_collectors()
    assert vitals.collect_vitals_live in collectors
    # And it honors the zero-arg collector contract.
    assert callable(vitals.collect_vitals_live)
