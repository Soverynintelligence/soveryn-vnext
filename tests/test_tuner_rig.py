"""Rig probe tests — injected readers, no GPU."""
from soveryn.platform.tuner.rig import Device, Rig, probe_rig

GB = 1024 ** 3


def test_probe_rig_builds_from_injected_readers():
    def devs():
        return [
            (0, "NVIDIA RTX PRO 5000 Blackwell", 48 * GB, "0000:45:00.0"),
            (1, "Quadro RTX 8000", 48 * GB, "0000:01:00.0"),
        ]
    rig = probe_rig(devices_reader=devs, ram_reader=lambda: 256 * GB)
    assert rig.total_ram_bytes == 256 * GB
    assert len(rig.devices) == 2
    d0 = rig.devices[0]
    assert (d0.index, d0.backend, d0.name, d0.vram_bytes, d0.pci_bus_id) == (
        0, "cuda", "NVIDIA RTX PRO 5000 Blackwell", 48 * GB, "0000:45:00.0")


def test_rig_and_device_are_frozen():
    d = Device(index=0, backend="cuda", name="x", vram_bytes=1, pci_bus_id="p")
    import dataclasses, pytest
    with pytest.raises(dataclasses.FrozenInstanceError):
        d.vram_bytes = 2
