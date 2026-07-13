"""`system_probe` — read-only host inventory (Component 1 of the gate design).

The verification gate needs the "this machine" fact-class to have a *source to
cite* instead of a gap to fill. `system_probe` is that source: a read-only
inventory of the live host, backed by a FIXED ALLOWLIST of commands.

Security boundary (mirrors the SSRF guard on `fetch_url`):
  - The `category` argument SELECTS a hardcoded command set. **No user input is
    ever interpolated into a command.** The only thing the caller controls is
    which allowlisted commands run — never their arguments, never a shell string.
  - Commands are run argv-style (list[str]), never through a shell. There is no
    string interpolation anywhere in this module.
  - Injectable `runner: Callable[[list[str]], str] | None` so tests never shell
    out and production stays deterministic about what executes.

`category ∈ {"gpu","cpu","mem","net","board","all"}`. Unknown categories raise
`ProbeError` (surfaced to the model as a tool-result error, not a crash).
"""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from soveryn.platform.tools.registry import ToolArgError, ToolRegistry, ToolSpec

Runner = Callable[[list[str]], str]

# ─────────────────────────────────────────────────────────────────────────────
# The allowlist. Each category maps to a tuple of (label, argv) commands. The
# argv lists are CONSTANT — the caller never contributes a token to them. DMI
# board identity is read from sysfs files (not a command) via _read_dmi.
# ─────────────────────────────────────────────────────────────────────────────

_GPU_CMD = (
    "nvidia-smi",
    "--query-gpu=name,driver_version,memory.total,pci.bus_id,compute_cap",
    "--format=csv,noheader",
)
_CPU_CMD = ("lscpu",)
_MEM_CMD = ("free", "-h")
_NET_CMD = ("lspci",)

# category → tuple[(label, argv)]
_ALLOWLIST: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "gpu": (("gpu", _GPU_CMD),),
    "cpu": (("cpu", _CPU_CMD),),
    "mem": (("mem", _MEM_CMD),),
    "net": (("net", _NET_CMD),),
    # board handled specially (DMI sysfs files), see _probe_board.
    "board": (),
}

# DMI board-identity files (read-only sysfs). No command, no interpolation.
_DMI_FILES: tuple[tuple[str, str], ...] = (
    ("board_vendor", "/sys/devices/virtual/dmi/id/board_vendor"),
    ("board_name", "/sys/devices/virtual/dmi/id/board_name"),
    ("board_version", "/sys/devices/virtual/dmi/id/board_version"),
    ("bios_vendor", "/sys/devices/virtual/dmi/id/bios_vendor"),
    ("bios_version", "/sys/devices/virtual/dmi/id/bios_version"),
)

VALID_CATEGORIES: frozenset[str] = frozenset({"gpu", "cpu", "mem", "net", "board", "all"})


class ProbeError(RuntimeError):
    """Raised for an invalid category or a probe that could not run."""


@dataclass(frozen=True)
class ProbeResult:
    """Structured host-inventory result.

    category  — the requested category.
    fields    — parsed key→value facts (best-effort structured view).
    raw       — the concatenated raw command output (the citable evidence).
    probed_at — ISO-8601 timestamp, caller/clock-stamped at probe time.
    """

    category: str
    fields: dict[str, str]
    raw: str
    probed_at: str


def _default_runner(argv: list[str]) -> str:
    """Run an allowlisted command argv-style (no shell) and return stdout.

    Never invoked with caller-supplied tokens — argv comes from `_ALLOWLIST`.
    """
    proc = subprocess.run(  # noqa: S603 — argv is allowlist-constant, no shell
        argv,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    out = proc.stdout or ""
    if proc.returncode != 0 and not out:
        err = (proc.stderr or "").strip()
        return f"[command failed: {' '.join(argv)}] {err}".strip()
    return out


def _read_dmi(reader: Callable[[str], str]) -> tuple[dict[str, str], str]:
    """Read DMI board-identity files. `reader` maps a path→contents (injectable).

    Missing/unreadable files are skipped (best-effort) rather than fatal.
    """
    fields: dict[str, str] = {}
    raw_parts: list[str] = []
    for key, path in _DMI_FILES:
        try:
            value = (reader(path) or "").strip()
        except (OSError, FileNotFoundError):
            continue
        if value:
            fields[key] = value
            raw_parts.append(f"{path}: {value}")
    return fields, "\n".join(raw_parts)


def _default_dmi_reader(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


# ─────────────────────────────────────────────────────────────────────────────
# Parsers — best-effort structured views over raw command output.
# ─────────────────────────────────────────────────────────────────────────────

def _parse_gpu(raw: str) -> dict[str, str]:
    """Parse `nvidia-smi --query-gpu=... --format=csv,noheader` rows."""
    fields: dict[str, str] = {}
    cols = ("name", "driver_version", "memory_total", "pci_bus_id", "compute_cap")
    idx = 0
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("["):
            continue
        parts = [p.strip() for p in line.split(",")]
        for col_i, col in enumerate(cols):
            if col_i < len(parts):
                fields[f"gpu{idx}.{col}"] = parts[col_i]
        idx += 1
    if idx:
        fields["gpu_count"] = str(idx)
    return fields


def _parse_kv_colon(raw: str) -> dict[str, str]:
    """Parse `key: value` lines (lscpu shape)."""
    fields: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if key and value:
            fields[key] = value
    return fields


def _parse_mem(raw: str) -> dict[str, str]:
    """Parse `free -h` — pull the Mem: and Swap: rows into fields."""
    fields: dict[str, str] = {}
    lines = raw.splitlines()
    header: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if not header and stripped.lower().startswith(("total", "mem", "swap")) is False:
            header = stripped.split()
            continue
        cols = stripped.split()
        if not cols:
            continue
        label = cols[0].rstrip(":").lower()
        if label in ("mem", "swap"):
            for h_i, val in enumerate(cols[1:]):
                col_name = header[h_i] if h_i < len(header) else f"col{h_i}"
                fields[f"{label}.{col_name}"] = val
    return fields


def _parse_net(raw: str) -> dict[str, str]:
    """Parse `lspci` — keep only network/ethernet controller lines."""
    fields: dict[str, str] = {}
    idx = 0
    for line in raw.splitlines():
        low = line.lower()
        if "ethernet" in low or "network controller" in low or "infiniband" in low:
            slot, _, desc = line.partition(" ")
            fields[f"net{idx}.slot"] = slot.strip()
            fields[f"net{idx}.desc"] = desc.strip()
            idx += 1
    if idx:
        fields["net_count"] = str(idx)
    return fields


_PARSERS: dict[str, Callable[[str], dict[str, str]]] = {
    "gpu": _parse_gpu,
    "cpu": _parse_kv_colon,
    "mem": _parse_mem,
    "net": _parse_net,
}


def run_system_probe(
    category: str = "all",
    *,
    runner: Runner | None = None,
    dmi_reader: Callable[[str], str] | None = None,
    now: Callable[[], datetime] | None = None,
) -> ProbeResult:
    """Probe the host for `category`. Read-only, allowlist-only.

    `runner`     — injectable command runner (tests pass canned output).
    `dmi_reader` — injectable path→contents reader for the board category.
    `now`        — injectable clock for `probed_at`.

    Raises ProbeError on an unknown category.
    """
    cat = (category or "all").lower().strip()
    if cat not in VALID_CATEGORIES:
        raise ProbeError(
            f"unknown category {category!r}; valid: {sorted(VALID_CATEGORIES)}"
        )
    run = runner or _default_runner
    read_dmi = dmi_reader or _default_dmi_reader
    clock = now or (lambda: datetime.now(timezone.utc))

    categories = ("gpu", "cpu", "mem", "net", "board") if cat == "all" else (cat,)

    all_fields: dict[str, str] = {}
    raw_parts: list[str] = []
    for c in categories:
        if c == "board":
            fields, raw = _read_dmi(read_dmi)
            all_fields.update(fields)
            if raw:
                raw_parts.append(f"# board (DMI)\n{raw}")
            continue
        for label, argv in _ALLOWLIST[c]:
            # argv is allowlist-constant; the caller contributes nothing to it.
            output = run(list(argv))
            raw_parts.append(f"# {label}: {' '.join(argv)}\n{output}")
            parser = _PARSERS.get(c)
            if parser is not None:
                all_fields.update(parser(output))

    return ProbeResult(
        category=cat,
        fields=all_fields,
        raw="\n\n".join(raw_parts),
        probed_at=clock().isoformat(timespec="seconds"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tool registration
# ─────────────────────────────────────────────────────────────────────────────

def build_system_probe_tool(
    *,
    owner_agent: str,
    runner: Runner | None = None,
) -> ToolSpec:
    """Build the `system_probe` ToolSpec for one owner agent.

    The handler validates that `category` is one of the allowlisted values
    (the registry's jsonschema `enum` also enforces this) and returns a
    JSON-serialisable dict view of the ProbeResult. No caller input ever
    reaches a command — `category` only selects a hardcoded command set.
    """

    def handler(args: Mapping[str, Any]) -> Any:
        category = args.get("category", "all")
        if not isinstance(category, str) or category.lower().strip() not in VALID_CATEGORIES:
            raise ToolArgError(
                f"category must be one of {sorted(VALID_CATEGORIES)} (got {category!r})"
            )
        try:
            result = run_system_probe(category, runner=runner)
        except ProbeError as e:
            return {"error": "probe_failed", "message": str(e)}
        return {
            "category": result.category,
            "fields": result.fields,
            "raw": result.raw,
            "probed_at": result.probed_at,
        }

    schema = {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "enum": sorted(VALID_CATEGORIES),
                "description": (
                    "Which host inventory to read: gpu, cpu, mem, net, board, "
                    "or all. Read-only; runs a fixed allowlist of commands."
                ),
                "default": "all",
            },
        },
        "required": [],
        "additionalProperties": False,
    }
    return ToolSpec(
        name="system_probe",
        owner=owner_agent,
        schema=schema,
        handler=handler,
        description=(
            "Read the LIVE host inventory (GPUs, CPU, memory, network, "
            "motherboard) from this machine, so facts about 'this box' have a "
            "real source instead of a guess. Read-only; backed by a fixed "
            "allowlist (nvidia-smi/lscpu/free/lspci/DMI). Use this to verify "
            "any claim about the hardware SOVERYN is running on."
        ),
    )


def register_system_probe_tool(
    registry: ToolRegistry,
    *,
    owner_agent: str,
    runner: Runner | None = None,
) -> None:
    """Register `system_probe` for one agent (Vett; Aetheria optional)."""
    registry.register(build_system_probe_tool(owner_agent=owner_agent, runner=runner))
