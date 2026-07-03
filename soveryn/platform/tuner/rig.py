"""The rig the tuner optimizes for. Rig/Device are pure data (the generator's
input); probe_rig() is the only hardware-touching bit and uses pynvml (already a
dependency of measure.py) so device numbering, VRAM, and PCIe bus IDs are read
robustly rather than by scraping nvidia-smi text.

pci_bus_id is captured for Layer 3's topology reasoning — it is NOT used by the
Layer-2 generator.
"""
from __future__ import annotations
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Device:
    index: int
    backend: str
    name: str
    vram_bytes: int
    pci_bus_id: str


@dataclass(frozen=True)
class Rig:
    devices: tuple[Device, ...]
    total_ram_bytes: int


def _pynvml_devices() -> list[tuple[int, str, int, str]]:
    """(index, name, total_vram_bytes, pci_bus_id) for each CUDA device."""
    import pynvml
    pynvml.nvmlInit()
    out: list[tuple[int, str, int, str]] = []
    for i in range(pynvml.nvmlDeviceGetCount()):
        h = pynvml.nvmlDeviceGetHandleByIndex(i)
        name = pynvml.nvmlDeviceGetName(h)
        if isinstance(name, bytes):
            name = name.decode()
        vram = int(pynvml.nvmlDeviceGetMemoryInfo(h).total)
        bus = pynvml.nvmlDeviceGetPciInfo(h).busId
        if isinstance(bus, bytes):
            bus = bus.decode()
        out.append((i, name, vram, bus))
    return out


def _system_ram_bytes() -> int:
    return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")


def probe_rig(*, devices_reader=_pynvml_devices, ram_reader=_system_ram_bytes) -> Rig:
    devices = tuple(
        Device(index=i, backend="cuda", name=name, vram_bytes=vram, pci_bus_id=bus)
        for (i, name, vram, bus) in devices_reader()
    )
    return Rig(devices=devices, total_ram_bytes=ram_reader())
