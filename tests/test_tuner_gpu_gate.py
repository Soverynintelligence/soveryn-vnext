"""Tuner GPU-occupancy gate.

The tuner launches candidate llama-servers on the rig's GPUs. If it spreads
onto GPUs the live fleet is already using, the candidates hang on the full
cards and starve the fleet (measured: Aetheria 0.55s -> 39.7s, and 3 CUDA-WDT
crashes). This gate refuses occupied GPUs so the tool enforces "fleet-down"
itself instead of relying on the operator to remember.
"""
from soveryn.platform.tuner.rig import (
    Device, Rig, free_devices, occupied_devices, select_rig,
)

GB = 1024 ** 3


def _dev(index, procs=0, used=0):
    return Device(index=index, backend="cuda", name=f"gpu{index}",
                  vram_bytes=48 * GB, pci_bus_id=f"0000:0{index}:00.0",
                  used_vram_bytes=used, compute_procs=procs)


def _rig(*devs):
    return Rig(devices=tuple(devs), total_ram_bytes=256 * GB)


def test_free_devices_excludes_those_with_compute_procs():
    rig = _rig(_dev(0, procs=0), _dev(1, procs=2), _dev(2, procs=0))
    assert [d.index for d in free_devices(rig)] == [0, 2]


def test_occupied_devices_lists_those_with_compute_procs():
    rig = _rig(_dev(0, procs=0), _dev(1, procs=2), _dev(2, procs=1))
    assert [d.index for d in occupied_devices(rig)] == [1, 2]


def test_select_rig_all_free_returns_full_rig_no_note():
    rig = _rig(_dev(0), _dev(1))
    used, note = select_rig(rig, allow_occupied=False)
    assert used is not None
    assert [d.index for d in used.devices] == [0, 1]
    assert note == ""


def test_select_rig_drops_occupied_and_reports_which():
    rig = _rig(_dev(0, procs=0), _dev(1, procs=3))
    used, note = select_rig(rig, allow_occupied=False)
    assert [d.index for d in used.devices] == [0]
    assert "1" in note and "skip" in note.lower()


def test_select_rig_refuses_when_all_occupied():
    rig = _rig(_dev(0, procs=1), _dev(1, procs=2))
    used, note = select_rig(rig, allow_occupied=False)
    assert used is None
    assert "occupied" in note.lower() and "fleet" in note.lower()


def test_select_rig_allow_occupied_override_uses_full_rig():
    rig = _rig(_dev(0, procs=1), _dev(1, procs=2))
    used, note = select_rig(rig, allow_occupied=True)
    assert used is not None
    assert [d.index for d in used.devices] == [0, 1]
    assert "allow-occupied" in note.lower()
