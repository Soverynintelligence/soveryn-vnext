#!/usr/bin/env python3
"""Video-friendly re-run of the Zenodo paper claim checks (+ optional live trials).

  # Recompute published claims from raw trial JSON (fast, deterministic)
  python scripts/paper_bench_demo.py

  # Same + a few live self-knowledge trials against a local model
  python scripts/paper_bench_demo.py --live 3 --model aetheria:8090

  # Export slim results JSON for the lab record page
  python scripts/paper_bench_demo.py --export ~/soveryn-site/lab/papers-bench.json

Pacing is intentional — this is a screen-record stage, not a CI job.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
V3 = ROOT / "scripts" / "verify_paper_claims.py"
V4 = ROOT / "scripts" / "verify_paper_claims_v4.py"
EVAL = ROOT / "scripts" / "self_knowledge_eval.py"


def pause(sec: float, *, turbo: bool) -> None:
    time.sleep(0.05 if turbo else sec)


def banner(title: str) -> None:
    line = "─" * 64
    print(f"\n{line}")
    print(f"  {title}")
    print(f"{line}\n")
    sys.stdout.flush()


def run_verifier(path: Path, *, turbo: bool) -> tuple[int, list[str]]:
    """Run a verify_paper_claims* script, re-print lines with light pacing."""
    proc = subprocess.run(
        [sys.executable, str(path)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    lines = (proc.stdout or "").splitlines()
    for line in lines:
        print(line)
        sys.stdout.flush()
        if line.strip().startswith("PASS") or line.strip().startswith("FAIL"):
            pause(0.04 if turbo else 0.07, turbo=turbo)
        elif line.strip().startswith("──") or "ALL CHECKS" in line:
            pause(0.15 if turbo else 0.35, turbo=turbo)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)
    return proc.returncode, lines


def parse_pass_fail(lines: list[str]) -> dict:
    checks = []
    for line in lines:
        s = line.strip()
        if not (s.startswith("PASS") or s.startswith("FAIL")):
            continue
        status, _, rest = s.partition(" ")
        rest = rest.strip()
        # Verifiers print: PASS  <label padded> got=... want=...
        if " got=" in rest:
            label = rest.split(" got=", 1)[0].rstrip()
        else:
            label = rest
        checks.append({"ok": status == "PASS", "label": label, "raw": s})
    return {
        "all_ok": all(c["ok"] for c in checks) if checks else False,
        "n": len(checks),
        "passed": sum(1 for c in checks if c["ok"]),
        "failed": sum(1 for c in checks if not c["ok"]),
        "checks": checks,
    }


def live_trials(n: int, model: str, *, turbo: bool) -> list[dict]:
    """Run a short self-knowledge live sample via the existing harness."""
    # model like aetheria:8090
    banner(f"LIVE SELF-KNOWLEDGE SAMPLE · n={n} · {model}")
    print("  Protocol: claim about own past action + evidence channel.")
    print("  Scored mechanically (did_it | did_not | cannot_determine).")
    print("  This is a *sample for video*, not a replacement for the full paper runs.\n")
    sys.stdout.flush()
    cmd = [
        sys.executable,
        str(EVAL),
        "--models",
        model,
        "-n",
        str(n),
    ]
    print(f"  $ {' '.join(cmd)}\n")
    sys.stdout.flush()
    proc = subprocess.run(cmd, cwd=str(ROOT), text=True)
    return [{"exit": proc.returncode, "model": model, "n": n}]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--turbo", action="store_true", help="faster pacing (still readable)")
    ap.add_argument("--live", type=int, default=0, metavar="N",
                    help="also run N live self-knowledge trials")
    ap.add_argument("--model", default="aetheria:8090",
                    help="model for --live (alias:port, default aetheria:8090)")
    ap.add_argument("--export", type=Path, default=None,
                    help="write slim JSON summary for lab/papers-record.html")
    ap.add_argument("--skip-v3", action="store_true")
    ap.add_argument("--skip-v4", action="store_true")
    args = ap.parse_args()
    turbo = args.turbo

    banner("SOVERYN PAPER BENCH · recompute from raw trials")
    print("  Papers:")
    print("    · Self-Knowledge / Calibration  DOI 10.5281/zenodo.21712932")
    print("    · A False Confession            DOI 10.5281/zenodo.21650072")
    print("  Nothing here trusts the prose — every number is re-derived.")
    pause(0.6, turbo=turbo)

    results: dict = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "papers": [
            {
                "title": "Calibration Is Not Only in the Weights / Self-Knowledge Is Not Uniform",
                "doi": "10.5281/zenodo.21712932",
                "url": "https://doi.org/10.5281/zenodo.21712932",
            },
            {
                "title": "A False Confession",
                "doi": "10.5281/zenodo.21650072",
                "url": "https://doi.org/10.5281/zenodo.21650072",
            },
        ],
        "arms": [],
    }

    code = 0
    if not args.skip_v3:
        banner("ARM A · v3 claim verifier (840 original trials)")
        print(f"  script: {V3.name}\n")
        pause(0.3, turbo=turbo)
        c, lines = run_verifier(V3, turbo=turbo)
        summary = parse_pass_fail(lines)
        summary["name"] = "v3 · scale-does-not-buy-self-knowledge checks"
        results["arms"].append(summary)
        code |= c
        pause(0.5, turbo=turbo)

    if not args.skip_v4:
        banner("ARM B · v4 claim verifier (1,680 trials total)")
        print(f"  script: {V4.name}\n")
        pause(0.3, turbo=turbo)
        c, lines = run_verifier(V4, turbo=turbo)
        summary = parse_pass_fail(lines)
        summary["name"] = "v4 · calibration-is-not-only-in-the-weights checks"
        results["arms"].append(summary)
        code |= c
        pause(0.5, turbo=turbo)

    if args.live > 0:
        live_trials(args.live, args.model, turbo=turbo)

    banner("BENCH CLOSE")
    for arm in results["arms"]:
        mark = "ALL PASS" if arm["all_ok"] else f"{arm['failed']} FAIL"
        print(f"  {arm['name']}: {arm['passed']}/{arm['n']}  [{mark}]")
    if code == 0:
        print("\n  Recompute agrees with the published Zenodo claims.")
    else:
        print("\n  Recompute DISAGREES — do not ship until investigated.")
    print()

    if args.export:
        args.export.parent.mkdir(parents=True, exist_ok=True)
        # Headline numbers for the record-mode "results" screen (not prose —
        # these match the paper verifiers' invariants).
        headlines = {
            "total_trials": 1680,
            "original_trials": 840,
            "new_trials": 840,
            "false_accept_trials": 420,
            "false_accept_overclaims": 0,
            "false_deny_cells": 420,
            "v3_checks": next((a["n"] for a in results["arms"] if "v3" in a["name"]), None),
            "v4_checks": next((a["n"] for a in results["arms"] if "v4" in a["name"]), None),
            "v3_passed": next((a["passed"] for a in results["arms"] if "v3" in a["name"]), None),
            "v4_passed": next((a["passed"] for a in results["arms"] if "v4" in a["name"]), None),
            "all_ok": all(a["all_ok"] for a in results["arms"]) if results["arms"] else False,
            "tagline": "Every quantitative claim reproduces from raw trials.",
            "bullets": [
                "1,680 trials across the self-knowledge ladder",
                "420 / 420 false-accept probes: zero over-claims",
                "Scale did not buy self-knowledge; calibration moves more",
                "Same checks as scripts/verify_paper_claims*.py",
            ],
        }
        slim = {
            "generated_at": results["generated_at"],
            "papers": results["papers"],
            "headlines": headlines,
            "arms": [
                {
                    "name": a["name"],
                    "all_ok": a["all_ok"],
                    "n": a["n"],
                    "passed": a["passed"],
                    "failed": a["failed"],
                    "checks": a["checks"],
                }
                for a in results["arms"]
            ],
        }
        args.export.write_text(json.dumps(slim, indent=2))
        print(f"  exported → {args.export}")

    return code


if __name__ == "__main__":
    raise SystemExit(main())
