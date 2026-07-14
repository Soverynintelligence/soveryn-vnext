"""Tests for soveryn/app/services/rig_stats.py.

rig_stats answers "what is actually running on each GPU" — a join of
`nvidia-smi --query-gpu` (identity/totals) with `nvidia-smi --query-compute-apps`
(pid -> gpu_uuid -> mem), with pid -> human name resolved directly from /proc
(never shelling out per-pid).
"""

import builtins
from unittest.mock import patch
import subprocess

_real_open = builtins.open

from soveryn.app.services.rig_stats import (
    get_rig_stats,
    _parse_gpu_list,
    _parse_compute_apps,
    _read_cmdline_alias,
    _read_cgroup_unit,
    _read_comm,
    _resolve_pid_name,
    Resident,
    RigGpu,
    RigStatsResult,
)

# Real-shape fixtures, verified on the box (see task-7-brief.md).
GPU_RAW = (
    "0, Quadro RTX 8000, GPU-50b41c93-aaaa, 965, 49152, 0, 48\n"
    "1, Quadro RTX 8000, GPU-305d1801-bbbb, 5099, 49152, 13, 47\n"
    "2, NVIDIA RTX PRO 5000 Blackwell, GPU-946b08b0-cccc, 45267, 48935, 0, 45\n"
)

# GPU 0 (Quadro #1) is idle: no compute-app rows reference its uuid at all.
# pid 218150 (vett-scotty) legitimately appears on TWO gpus.
APPS_RAW = (
    "46765, 43086, GPU-946b08b0-cccc\n"
    "218150, 28978, GPU-305d1801-bbbb\n"
    "218150, 1474, GPU-946b08b0-cccc\n"
)


def _name_lookup(pid: int) -> str | None:
    return {46765: "aetheria", 218150: "vett-scotty"}.get(pid)


def _smi(stdout: str = "", rc: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr="")


# --- parsing -----------------------------------------------------------

def test_parse_gpu_list_three_gpus():
    rows = _parse_gpu_list(GPU_RAW)
    assert len(rows) == 3
    assert rows[0]["index"] == 0
    assert rows[0]["name"] == "Quadro RTX 8000"
    assert rows[0]["uuid"] == "GPU-50b41c93-aaaa"
    assert rows[0]["mem_used_mib"] == 965
    assert rows[0]["mem_total_mib"] == 49152
    assert rows[2]["name"] == "NVIDIA RTX PRO 5000 Blackwell"
    assert rows[2]["temp_c"] == 45


def test_parse_gpu_list_skips_unparseable_row_instead_of_faking_zero():
    raw = GPU_RAW + "3, Bad Row, GPU-zzzz, notanumber, 49152, 0, 40\n"
    rows = _parse_gpu_list(raw)
    assert len(rows) == 3  # the bad row is dropped, not zero-filled


def test_parse_compute_apps_keeps_duplicate_pid_on_two_gpus():
    """A pid appearing on two gpu rows must produce TWO rows, not one."""
    rows = _parse_compute_apps(APPS_RAW)
    assert len(rows) == 3
    pids = [r[0] for r in rows]
    assert pids.count(218150) == 2


def test_parse_compute_apps_empty():
    assert _parse_compute_apps("") == []


# --- name resolution -----------------------------------------------------

def test_alias_wins_over_cgroup():
    with patch("soveryn.app.services.rig_stats._read_cmdline_alias", return_value="aetheria"), \
         patch("soveryn.app.services.rig_stats._read_cgroup_unit", return_value="some-other-unit"), \
         patch("soveryn.app.services.rig_stats._read_comm", return_value="comm-name"):
        assert _resolve_pid_name(12345) == "aetheria"


def test_cgroup_unit_used_when_no_alias():
    with patch("soveryn.app.services.rig_stats._read_cmdline_alias", return_value=None), \
         patch("soveryn.app.services.rig_stats._read_cgroup_unit", return_value="f5tts"), \
         patch("soveryn.app.services.rig_stats._read_comm", return_value="comm-name"):
        assert _resolve_pid_name(12345) == "f5tts"


def test_comm_is_last_fallback():
    with patch("soveryn.app.services.rig_stats._read_cmdline_alias", return_value=None), \
         patch("soveryn.app.services.rig_stats._read_cgroup_unit", return_value=None), \
         patch("soveryn.app.services.rig_stats._read_comm", return_value="python3"):
        assert _resolve_pid_name(12345) == "python3"


def test_read_cmdline_alias_parses_nul_separated_flag(tmp_path):
    fake = tmp_path / "cmdline"
    fake.write_bytes(b"llama-server\x00--alias\x00vett-scotty\x00--port\x008080\x00")
    with patch("builtins.open", lambda *a, **k: _real_open(fake, "rb")):
        assert _read_cmdline_alias(999) == "vett-scotty"


def test_read_cmdline_alias_none_when_flag_absent(tmp_path):
    fake = tmp_path / "cmdline"
    fake.write_bytes(b"some-binary\x00--port\x008080\x00")
    with patch("builtins.open", lambda *a, **k: _real_open(fake, "rb")):
        assert _read_cmdline_alias(999) is None


def test_read_cgroup_unit_strips_soveryn_prefix_and_service_suffix(tmp_path):
    fake = tmp_path / "cgroup"
    fake.write_text("0::/system.slice/soveryn-f5tts.service\n")
    with patch("builtins.open", lambda *a, **k: _real_open(fake, "r")):
        assert _read_cgroup_unit(999) == "f5tts"


def test_read_cgroup_unit_without_soveryn_prefix(tmp_path):
    fake = tmp_path / "cgroup"
    fake.write_text("0::/system.slice/parakeet.service\n")
    with patch("builtins.open", lambda *a, **k: _real_open(fake, "r")):
        assert _read_cgroup_unit(999) == "parakeet"


def test_read_comm_strips_whitespace(tmp_path):
    fake = tmp_path / "comm"
    fake.write_text("python3\n")
    with patch("builtins.open", lambda *a, **k: _real_open(fake, "r")):
        assert _read_comm(999) == "python3"


def test_pid_vanished_between_calls_is_skipped_not_fatal():
    """All three /proc reads raise FileNotFoundError -> resolves to None, caller skips."""
    with patch("builtins.open", side_effect=FileNotFoundError()):
        assert _read_cmdline_alias(999) is None
        assert _read_cgroup_unit(999) is None
        assert _read_comm(999) is None
        assert _resolve_pid_name(999) is None


# --- full join / get_rig_stats -------------------------------------------

def test_join_attaches_residents_to_correct_gpu_by_uuid_and_sorts_desc():
    with patch("subprocess.run", side_effect=[_smi(GPU_RAW), _smi(APPS_RAW)]), \
         patch("soveryn.app.services.rig_stats._resolve_pid_name", side_effect=_name_lookup):
        r = get_rig_stats(_force_refresh=True)

    assert r.available is True
    assert len(r.gpus) == 3
    by_index = {g.index: g for g in r.gpus}

    # Blackwell (index 2): aetheria 43086 + vett-scotty 1474, sorted desc.
    blackwell = by_index[2]
    assert blackwell.uuid == "GPU-946b08b0-cccc"
    assert blackwell.residents == [
        Resident(name="aetheria", mem_mib=43086),
        Resident(name="vett-scotty", mem_mib=1474),
    ]

    # Quadro #2 (index 1): vett-scotty only.
    quadro2 = by_index[1]
    assert quadro2.residents == [Resident(name="vett-scotty", mem_mib=28978)]


def test_pid_on_two_gpus_produces_a_resident_row_on_both_not_deduped():
    with patch("subprocess.run", side_effect=[_smi(GPU_RAW), _smi(APPS_RAW)]), \
         patch("soveryn.app.services.rig_stats._resolve_pid_name", side_effect=_name_lookup):
        r = get_rig_stats(_force_refresh=True)

    names_by_gpu = {g.index: [res.name for res in g.residents] for g in r.gpus}
    assert "vett-scotty" in names_by_gpu[1]
    assert "vett-scotty" in names_by_gpu[2]


def test_idle_gpu_yields_empty_residents_list():
    """GPU 0 has no compute-app rows referencing its uuid at all — this is the
    whole reason the panel exists (a full card sitting idle unnoticed)."""
    with patch("subprocess.run", side_effect=[_smi(GPU_RAW), _smi(APPS_RAW)]), \
         patch("soveryn.app.services.rig_stats._resolve_pid_name", side_effect=_name_lookup):
        r = get_rig_stats(_force_refresh=True)

    idle = next(g for g in r.gpus if g.index == 0)
    assert idle.residents == []


def test_unresolvable_pid_is_dropped_from_residents():
    with patch("subprocess.run", side_effect=[_smi(GPU_RAW), _smi(APPS_RAW)]), \
         patch("soveryn.app.services.rig_stats._resolve_pid_name", return_value=None):
        r = get_rig_stats(_force_refresh=True)

    for g in r.gpus:
        assert g.residents == []


def test_get_rig_stats_falls_back_when_smi_missing():
    with patch("subprocess.run", side_effect=FileNotFoundError("nvidia-smi")):
        r = get_rig_stats(_force_refresh=True)
    assert r.available is False
    assert r.gpus == []
    assert "not available" in r.message.lower()


def test_get_rig_stats_falls_back_on_nonzero_exit():
    with patch("subprocess.run", return_value=_smi("", rc=9)):
        r = get_rig_stats(_force_refresh=True)
    assert r.available is False
    assert r.gpus == []


def test_get_rig_stats_caches_within_window():
    with patch("subprocess.run", side_effect=[_smi(GPU_RAW), _smi(APPS_RAW)]) as mock_run, \
         patch("soveryn.app.services.rig_stats._resolve_pid_name", side_effect=_name_lookup):
        get_rig_stats(_force_refresh=True)
        get_rig_stats()  # cached
        get_rig_stats()  # cached
    assert mock_run.call_count == 2  # one gpu-list call + one compute-apps call, exactly once
