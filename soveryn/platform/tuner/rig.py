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
    used_vram_bytes: int = 0   # VRAM currently in use (any workload)
    compute_procs: int = 0     # count of CUDA COMPUTE processes on this device
    #                            (graphics/display procs are NOT counted, so an
    #                            X-server on a card does not mark it occupied)


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


def _pynvml_occupancy() -> dict[int, tuple[int, int]]:
    """{index: (used_vram_bytes, compute_process_count)} per CUDA device.

    Uses COMPUTE-running processes (llama-server etc.), not graphics — so an
    X-server driving a display does not make its card read as occupied.
    """
    import pynvml
    pynvml.nvmlInit()
    out: dict[int, tuple[int, int]] = {}
    for i in range(pynvml.nvmlDeviceGetCount()):
        h = pynvml.nvmlDeviceGetHandleByIndex(i)
        used = int(pynvml.nvmlDeviceGetMemoryInfo(h).used)
        try:
            procs = pynvml.nvmlDeviceGetComputeRunningProcesses(h)
        except pynvml.NVMLError:
            procs = []
        out[i] = (used, len(procs))
    return out


def probe_rig(*, devices_reader=_pynvml_devices, ram_reader=_system_ram_bytes,
              occupancy_reader=_pynvml_occupancy) -> Rig:
    occ = occupancy_reader()
    devices = tuple(
        Device(index=i, backend="cuda", name=name, vram_bytes=vram, pci_bus_id=bus,
               used_vram_bytes=occ.get(i, (0, 0))[0],
               compute_procs=occ.get(i, (0, 0))[1])
        for (i, name, vram, bus) in devices_reader()
    )
    return Rig(devices=devices, total_ram_bytes=ram_reader())


# ── occupancy gate (pure; the CLI enforces "don't tune on the live fleet") ──
def free_devices(rig: Rig) -> tuple[Device, ...]:
    """Devices with no CUDA compute process running on them."""
    return tuple(d for d in rig.devices if d.compute_procs == 0)


def occupied_devices(rig: Rig) -> tuple[Device, ...]:
    """Devices a live workload is already computing on."""
    return tuple(d for d in rig.devices if d.compute_procs > 0)


def select_rig(rig: Rig, allow_occupied: bool) -> tuple[Rig | None, str]:
    """Decide which rig the tuner may use.

    Returns (rig_to_use, note). rig_to_use is None => REFUSE (all GPUs busy).
    Default: drop occupied GPUs, tune only on free ones; refuse if none free.
    allow_occupied=True: use the full rig (override), with a loud warning.
    """
    occupied = occupied_devices(rig)
    if allow_occupied:
        note = ""
        if occupied:
            note = (f"--allow-occupied: tuning on {len(occupied)} OCCUPIED GPU(s) "
                    f"{[d.index for d in occupied]} — this can stall the live fleet.")
        return rig, note
    free = free_devices(rig)
    if not free:
        idx = [d.index for d in occupied]
        return None, (
            f"REFUSING: all {len(rig.devices)} GPU(s) {idx} are occupied by compute "
            f"processes — the fleet appears live. Stop the fleet first, or pass "
            f"--allow-occupied to override (may stall running models).")
    note = ""
    if occupied:
        note = (f"skipping {len(occupied)} occupied GPU(s) "
                f"{[d.index for d in occupied]}; tuning on free GPU(s) "
                f"{[d.index for d in free]}.")
    return Rig(devices=free, total_ram_bytes=rig.total_ram_bytes), note
