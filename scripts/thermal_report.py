#!/usr/bin/env python3
"""Read the thermal log back: what is hottest, and is it trending?

    python3 scripts/thermal_report.py            # last 24h
    python3 scripts/thermal_report.py --hours 6
"""
from __future__ import annotations
import argparse, json, pathlib, statistics, time, glob

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load(hours: float):
    cutoff = time.time() - hours * 3600
    rows = []
    for f in sorted(glob.glob(str(ROOT / "data" / "thermal" / "*.jsonl"))):
        for line in pathlib.Path(f).read_text().splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("epoch", 0) >= cutoff:
                rows.append(r)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=24)
    a = ap.parse_args()
    rows = load(a.hours)
    if not rows:
        print("no samples in that window yet"); return 0

    print(f"  {len(rows)} samples over {a.hours:g}h "
          f"({rows[0]['ts']} → {rows[-1]['ts']})\n")

    series: dict[str, list[float]] = {}
    for r in rows:
        for k, v in r.get("hwmon", {}).items():
            series.setdefault(k, []).append(v)
        for g in r.get("gpu", []):
            if g.get("temp_c") is not None:
                series.setdefault(f"gpu{g['idx']}.temp", []).append(g["temp_c"])
            if g.get("fan_pct") is not None:
                series.setdefault(f"gpu{g['idx']}.fan%", []).append(g["fan_pct"])

    print(f"  {'sensor':34} {'now':>6} {'mean':>6} {'max':>6} {'trend':>7}")
    for k, vals in sorted(series.items(), key=lambda x: -max(x[1])):
        half = max(1, len(vals) // 2)
        drift = statistics.fmean(vals[half:]) - statistics.fmean(vals[:half])
        arrow = "→" if abs(drift) < 1 else ("↑" if drift > 0 else "↓")
        print(f"  {k:34} {vals[-1]:6.1f} {statistics.fmean(vals):6.1f} "
              f"{max(vals):6.1f} {arrow}{abs(drift):5.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
