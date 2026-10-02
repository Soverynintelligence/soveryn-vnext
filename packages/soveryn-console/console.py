#!/usr/bin/env python3
"""SOVERYN Console — Jarvis-style HUD for the house.

Textual TUI. Reads the same truth the CLI does:
  ~/.soveryn/kernel_brain      active brain id
  config/soveryn-cli/profiles.json   profiles + endpoints
  nvidia-smi                   GPU live state
  systemctl --user             seat services
and runs real commands through the CLI (`soveryn ...`, `kernel ...`)
in an input bar, streaming output into the log panel.

Usage:
  soveryn-console            # TUI
  soveryn-console --once     # snapshot print (no TUI; CI-friendly)
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
BRAIN_FILE = HOME / ".soveryn" / "kernel_brain"
PROFILES = HOME / "soveryn_vnext" / "config" / "soveryn-cli" / "profiles.json"

ENDPOINTS = {
    "kernel GLM fold": "http://10.10.10.2:8001/v1/models",
    "eve NVFP4 :8090": "http://127.0.0.1:8090/v1/models",
    "quadro router :8091": "http://127.0.0.1:8091/v1/models",
    "embeddings :8096": "http://127.0.0.1:8096/health",
    "vnext :5001": "http://127.0.0.1:5001/health",
    "stt :8087": "http://127.0.0.1:8087/health",
    "tts :8088": "http://127.0.0.1:8088/healthz",
}

SEAT_UNITS = [
    "soveryn-nvfp4-vllm",
    "soveryn-vnext",
    "soveryn-router-quadro",
    "soveryn-embeddings",
]


def read_brain() -> str:
    try:
        return BRAIN_FILE.read_text().strip()
    except OSError:
        return "unknown"


def read_profile_endpoint(brain: str) -> str:
    try:
        cfg = json.loads(PROFILES.read_text())
        prof = (cfg.get("profiles") or {}).get(brain) or {}
        return prof.get("baseUrl") or prof.get("endpoint") or "?"
    except Exception:
        return "?"


def probe(url: str, timeout: float = 1.2) -> str:
    """Any HTTP response (any status) = the seat is alive; only connection
    failure means DOWN. 404 on a wrong path is a console bug, not an outage."""
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return "OK" if r.status < 500 else f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}"
    except Exception:
        return "DOWN"


def gpu_lines() -> list[str]:
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=index,name,memory.used,memory.total,utilization.gpu,temperature.gpu",
             "--format=csv,noheader"], text=True, timeout=5)
        return [l.strip() for l in out.strip().splitlines()]
    except Exception as e:
        return [f"nvidia-smi unavailable: {e}"]


def seat_states() -> list[str]:
    rows = []
    for u in SEAT_UNITS:
        try:
            st = subprocess.check_output(
                ["systemctl", "--user", "is-active", f"{u}.service"],
                text=True, timeout=3).strip()
        except Exception:
            st = "unknown"
        rows.append(f"{u}: {st}")
    return rows


def snapshot() -> str:
    """Plain-text snapshot (used by --once and by the TUI panels)."""
    brain = read_brain()
    lines = []
    lines.append(f"[bold cyan]BRAIN[/]  {brain}  ->  {read_profile_endpoint(brain)}")
    lines.append("")
    lines.append("[bold cyan]ENDPOINTS[/]")
    lines.append(endpoints_text("  "))
    lines.append("")
    lines.append("[bold cyan]GPUs[/]")
    for l in gpu_lines():
        lines.append(f"  {l}")
    lines.append("")
    lines.append("[bold cyan]SEATS[/]")
    for l in seat_states():
        lines.append(f"  {l}")
    return "\n".join(lines)


def endpoints_text(pad: str = "") -> str:
    """Just the probed endpoint lines (shared by snapshot and the TUI panel)."""
    lines = []
    for name, url in ENDPOINTS.items():
        state = probe(url)
        mark = "[green]●[/]" if state == "OK" else "[red]○[/]"
        lines.append(f"{pad}{mark} {name:<22} {state}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(prog="soveryn-console")
    ap.add_argument("--once", action="store_true", help="print snapshot and exit")
    args = ap.parse_args()
    if args.once:
        from rich.console import Console
        Console().print(snapshot())
        return 0
    from soveryn_console_app import SoverynConsoleApp
    return SoverynConsoleApp().run() or 0


if __name__ == "__main__":
    sys.exit(main())
