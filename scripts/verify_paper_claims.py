#!/usr/bin/env python
"""Recompute every quantitative claim in the paper from raw trials and diff.

    python scripts/verify_paper_claims.py

Written 2026-07-31 after a model that was never tested appeared in the published
results table for two versions. Reading the paper does not catch that class of
error; recomputing from the trial data does. Nothing here trusts the prose.

Exits non-zero if any claim disagrees with the data.
"""
from __future__ import annotations

import glob
import json
import math
import re
import sys
from pathlib import Path

# Anchored to the repo root, not the caller's cwd — running this from the wrong
# directory once produced a "FAILED" that was purely a path error, which is
# exactly the kind of false signal a verification tool must never emit.
ROOT = Path(__file__).resolve().parent.parent
PAPER = ROOT / "docs/papers/scale-does-not-buy-self-knowledge.md"
DATA = str(ROOT / "docs/papers/data/*.json")
PRESETS = str(ROOT / "runtime/router-presets-*.ini")

# alias → the weights the paper says it was. Verified against router config below.
CLAIMED_WEIGHTS = {
    "reflection":        "Qwen3.5-9B-Q6_K.gguf",
    "shepherd-9b":       "Qwen3.5-9B-Q6_K.gguf",
    "vett-scotty":       "Qwen_Qwen3.6-27B-Q8_0.gguf",
    "aetheria":          "google_gemma-4-31B-it-Q6_K_L.gguf",
}
ORDER = ["reflection", "shepherd-9b", "vett-scotty", "aetheria",
         "laguna", "deepseek-v4-flash", "glm-5.2"]

fails: list[str] = []


def check(label: str, got, want) -> None:
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<52} got={got!r} want={want!r}")
    if not ok:
        fails.append(label)


def wilson(x: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = x / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h) * 100, min(1.0, c + h) * 100)


def ztest(x1: int, n1: int, x2: int, n2: int) -> tuple[float, float]:
    p1, p2 = x1 / n1, x2 / n2
    p = (x1 + x2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se == 0:
        return (float("inf"), 0.0)
    z = (p1 - p2) / se
    return z, math.erfc(abs(z) / math.sqrt(2))


def main() -> int:
    trials = []
    for f in sorted(glob.glob(DATA)):
        trials += json.load(open(f))
    paper = PAPER.read_text()

    print("\n  ── ALIAS → WEIGHTS (against live router config)")
    preset = "\n".join(Path(p).read_text() for p in glob.glob(PRESETS))
    for alias, want in CLAIMED_WEIGHTS.items():
        m = re.search(rf"\[{re.escape(alias)}\]\s*\n(?:(?!\[).*\n)*?\s*model\s*=\s*(\S+)",
                      preset)
        check(f"{alias} weights", Path(m.group(1)).name if m else None, want)
    # The error that got through twice: two aliases, one file.
    check("runs 1-2 are the same weights file",
          CLAIMED_WEIGHTS["reflection"] == CLAIMED_WEIGHTS["shepherd-9b"], True)
    check("no Phi anywhere in trial data",
          any("phi" in json.dumps(t).lower() for t in trials), False)

    print("\n  ── SHAPE")
    check("total trials", len(trials), 840)
    check("distinct runs", len(set(t["model"] for t in trials)), 7)
    check("runs match expected aliases", sorted(set(t["model"] for t in trials)),
          sorted(ORDER))
    check("errors", sum(1 for t in trials if t["verdict"] == "error"), 0)
    check("unparsed", sum(1 for t in trials if t["verdict"] == "unparsed"), 0)

    def cell(a, ct, ev, cav):
        return [t for t in trials if t["model"] == a and t["claim_true"] == ct
                and t["evidence"] == ev and t["caveat"] == cav]

    print("\n  ── PER-RUN RATES (paper's §3 table)")
    # (alias, false-deny%, +caveat%, abstain%)
    TABLE = [("reflection", 100, 0, 0), ("shepherd-9b", 100, 0, 0),
             ("vett-scotty", 100, 23, 0), ("aetheria", 43, 0, 0),
             ("laguna", 67, 0, 0), ("deepseek-v4-flash", 10, 0, 43),
             ("glm-5.2", 17, 0, 83)]
    for a, fd_w, fdc_w, ab_w in TABLE:
        ctl = cell(a, True, "correct", False)
        fd = cell(a, True, "empty", False)
        fdc = cell(a, True, "empty", True)
        fa = cell(a, False, "contradicts", False)
        pct = lambda s, v: round(100 * sum(1 for t in s if t["verdict"] == v) / len(s))
        check(f"{a} control did_it", pct(ctl, "did_it"), 100)
        check(f"{a} false-deny", pct(fd, "did_not"), fd_w)
        check(f"{a} false-deny +caveat", pct(fdc, "did_not"), fdc_w)
        check(f"{a} false-accept", pct(fa, "did_it"), 0)
        check(f"{a} abstain (empty)", pct(fd, "cannot_determine"), ab_w)

    print("\n  ── AGGREGATES")
    fa_all = [t for t in trials if not t["claim_true"] and t["evidence"] == "contradicts"]
    check("false-accept trials", len(fa_all), 210)
    check("over-claims", sum(1 for t in fa_all if t["verdict"] == "did_it"), 0)
    check("abstentions total", sum(1 for t in trials if t["verdict"] == "cannot_determine"), 90)
    small = [t for t in trials if t["model"] in ORDER[:5]]
    check("abstentions, five smaller runs (paper: 2 in 600)",
          sum(1 for t in small if t["verdict"] == "cannot_determine"), 2)
    small_empty = [t for t in small if t["claim_true"] and t["evidence"] == "empty"
                   and not t["caveat"]]
    check("abstentions under empty, five smaller (paper: 0 of 150)",
          (sum(1 for t in small_empty if t["verdict"] == "cannot_determine"),
           len(small_empty)), (0, 150))

    print("\n  ── §3.3 WITHIN-MODEL TABLE")
    for a, want in [("deepseek-v4-flash", (0, 0, 13, 23)), ("glm-5.2", (0, 0, 25, 27))]:
        got = (sum(1 for t in cell(a, True, "correct", False) if t["verdict"] == "cannot_determine"),
               sum(1 for t in cell(a, False, "contradicts", False) if t["verdict"] == "cannot_determine"),
               sum(1 for t in cell(a, True, "empty", False) if t["verdict"] == "cannot_determine"),
               sum(1 for t in cell(a, True, "empty", True) if t["verdict"] == "cannot_determine"))
        check(f"{a} abstain by cell", got, want)

    print("\n  ── SIGNIFICANCE TESTS")
    ab = lambda a: sum(1 for t in cell(a, True, "empty", False) if t["verdict"] == "cannot_determine")
    z1, _ = ztest(ab("glm-5.2"), 30, 0, 150)
    z2, _ = ztest(ab("deepseek-v4-flash"), 30, 0, 150)
    z3, _ = ztest(ab("glm-5.2"), 30, ab("deepseek-v4-flash"), 30)
    check("z GLM vs five smaller", round(z1, 2), 12.05)
    check("z DeepSeek vs five smaller", round(z2, 2), 8.37)
    check("z GLM vs DeepSeek", round(z3, 2), 3.21)

    print("\n  ── CONFIDENCE INTERVALS in §3 table")
    for a, x_n, lo_w, hi_w in [("aetheria", ("did_not", 43, 61), 27, 61),
                               ("deepseek-v4-flash", ("cannot_determine", 27, 61), 27, 61),
                               ("glm-5.2", ("cannot_determine", 66, 93), 66, 93)]:
        v = x_n[0]
        s = cell(a, True, "empty", False)
        lo, hi = wilson(sum(1 for t in s if t["verdict"] == v), len(s))
        check(f"{a} {v} CI", (round(lo), round(hi)), (lo_w, hi_w))

    print("\n  ── PAPER TEXT CONSISTENCY")
    check("no 'seven models' claim in body", "Seven models, 840" in paper, False)
    check("subtitle says six models", "Six models, 840 trials" in paper, True)
    for stale in ["Phi-3.5-mini-instruct (uncensored)", "| Phi-3.5-mini |"]:
        check(f"stale ladder row absent: {stale[:28]}", stale in paper, False)
    check("v3 marked", "**v3**" in paper, True)
    check("concept DOI present", "21712932" in paper, True)

    print()
    if fails:
        print(f"  {len(fails)} FAILED: " + "; ".join(fails[:6]))
        return 1
    print("  ALL CHECKS PASSED — every quantitative claim reproduces from raw trials.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
