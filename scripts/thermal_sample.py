#!/usr/bin/env python3
"""Sample every temperature the tower will tell us about, append one JSON line.

Why this exists: "the fans are running longer than they used to" is a real
signal and an unanswerable one without history. Point-in-time readings cannot
distinguish a hot afternoon from a trend. This makes the question answerable.

Reads only sysfs and nvidia-smi — no root, no lm-sensors, no daemon.
Appends to data/thermal/YYYY-MM.jsonl so a month is one greppable file.
"""
from __future__ import annotations
import json, pathlib, subprocess, time, glob, os

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT  = ROOT / "data" / "thermal"


def hwmon() -> dict:
    """CPU, NVMe, NICs — whatever the kernel exposes."""
    out: dict[str, float] = {}
    for d in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        try:
            name = pathlib.Path(d, "name").read_text().strip()
        except OSError:
            continue
        for f in sorted(glob.glob(f"{d}/temp*_input")):
            try:
                v = int(pathlib.Path(f).read_text()) / 1000.0
            except (OSError, ValueError):
                continue
            lbl_path = f.replace("_input", "_label")
            label = (pathlib.Path(lbl_path).read_text().strip()
                     if os.path.exists(lbl_path)
                     else pathlib.Path(f).name.replace("_input", ""))
            # Two NICs of the same model both report "temp1"; disambiguate by
            # hwmon index so they don't collapse into one another.
            key = f"{name}.{label}".replace(" ", "_")
            if key in out:
                key = f"{key}.{pathlib.Path(d).name}"
            out[key] = round(v, 1)
    return out


def gpus() -> list[dict]:
    q = ("index,name,temperature.gpu,fan.speed,power.draw,"
         "utilization.gpu,memory.used,clocks.sm")
    try:
        raw = subprocess.run(
            ["nvidia-smi", f"--query-gpu={q}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=15).stdout
    except Exception:
        return []
    rows = []
    for line in raw.strip().splitlines():
        p = [x.strip() for x in line.split(",")]
        if len(p) < 8:
            continue
        def num(x):
            try: return float(x)
            except ValueError: return None
        rows.append({"idx": int(p[0]), "name": p[1], "temp_c": num(p[2]),
                     "fan_pct": num(p[3]), "power_w": num(p[4]),
                     "util_pct": num(p[5]), "mem_mib": num(p[6]),
                     "sm_mhz": num(p[7])})
    return rows


def main() -> int:
    la1, la5, la15 = os.getloadavg()
    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "epoch": int(time.time()),
        "load": [round(la1, 2), round(la5, 2), round(la15, 2)],
        "hwmon": hwmon(),
        "gpu": gpus(),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / (time.strftime("%Y-%m") + ".jsonl")
    with path.open("a") as fh:
        fh.write(json.dumps(rec) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
