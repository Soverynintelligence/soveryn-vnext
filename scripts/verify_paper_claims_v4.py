#!/usr/bin/env python
"""Recompute every quantitative claim in v4 from raw trials and diff.

    python scripts/verify_paper_claims_v4.py

Companion to verify_paper_claims.py, which pins v3. That one stays as it is: it
guards the 840 original trials, and v4 changes none of them. This one guards the
840 new ones and every claim built on both.

v4 withdraws v3's headline. A version that withdraws a claim has to be at least
as checkable as the one it corrects, or the correction is just a different
assertion. Nothing here trusts the prose.

Exits non-zero if any claim disagrees with the data.
"""
from __future__ import annotations

import glob
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAPER = ROOT / "docs/papers/calibration-is-not-only-in-the-weights.md"
DATA = str(ROOT / "docs/papers/data/*.json")

# Which files were run with reasoning enabled. This is the single most
# load-bearing fact in v4 and it is not recorded in the trial rows, so it is
# declared here and cross-checked against latency and non-termination below —
# a reasoning-enabled run cannot look like a reasoning-off one.
REASONING_ON = {
    "selfknow_thinking_small.json",
    "selfknow_thinking_27b_clean.json",
    "selfknow_thinking_27b_8k.json",
    "selfknow_deepseek_0731_thinking.json",
}

VALID = {"did_it", "did_not", "cannot_determine"}

fails: list[str] = []


def check(label: str, got, want) -> None:
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<56} got={got!r} want={want!r}")
    if not ok:
        fails.append(label)


def ztest(x1: int, n1: int, x2: int, n2: int) -> tuple[float, float]:
    p1, p2 = x1 / n1, x2 / n2
    p = (x1 + x2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se == 0:
        return (float("inf"), 0.0)
    z = (p1 - p2) / se
    return z, math.erfc(abs(z) / math.sqrt(2))


def load() -> dict[str, list[dict]]:
    out = {}
    for f in sorted(glob.glob(DATA)):
        out[Path(f).name] = json.load(open(f))
    return out


def cells(rows: list[dict], model: str | None = None) -> dict[str, list[dict]]:
    """Split one run into the four probe cells."""
    sel = [r for r in rows if model is None or r["model"] == model]
    return {
        "control": [r for r in sel if r["evidence"] == "correct"],
        "deny": [r for r in sel if r["evidence"] == "empty" and not r["caveat"]],
        "deny_caveat": [r for r in sel if r["evidence"] == "empty" and r["caveat"]],
        "false_accept": [r for r in sel if r["evidence"] == "contradicts"],
    }


def count(rows: list[dict], verdict: str) -> int:
    return sum(1 for r in rows if r["verdict"] == verdict)


def main() -> int:
    files = load()
    everything = [r for rows in files.values() for r in rows]
    paper = PAPER.read_text()

    print("\n  ── SHAPE")
    check("total trials", len(everything), 1680)
    check("original trials preserved",
          sum(len(files[f]) for f in
              ["selfknow.json", "selfknow_laguna.json",
               "selfknow_deepseek_144gb.json", "selfknow_glm52_340gb.json"]), 840)
    check("new trials added", len(everything) - 840, 840)

    print("\n  ── §4.1  OVER-CLAIMING, ACROSS EVERY TRIAL EVER RUN")
    fa = [r for r in everything if r["evidence"] == "contradicts"]
    check("false-accept trials", len(fa), 420)
    check("over-claims (paper: 420 for 420)", count(fa, "did_it"), 0)

    print("\n  ── §4.2  REASONING AT 6.9 GB  (Qwen3.5-9B)")
    off = cells(files["selfknow.json"], "shepherd-9b")
    on = cells(files["selfknow_thinking_small.json"], "shepherd-9b")
    check("OFF control did_it", count(off["control"], "did_it"), 30)
    check("ON  control did_it", count(on["control"], "did_it"), 30)
    check("OFF false-deny denied (paper: 30/30)", count(off["deny"], "did_not"), 30)
    check("ON  false-deny denied (paper: 20/30)", count(on["deny"], "did_not"), 20)
    check("ON  false-deny abstained (paper: 10)",
          count(on["deny"], "cannot_determine"), 10)
    check("OFF caveat abstained (paper: 0)",
          count(off["deny_caveat"], "cannot_determine"), 0)
    check("ON  caveat abstained (paper: 27/30 = 90%)",
          count(on["deny_caveat"], "cannot_determine"), 27)
    # Pooled across both empty-channel cells — the paper's headline for §4.2.
    off_empty = off["deny"] + off["deny_caveat"]
    on_empty = on["deny"] + on["deny_caveat"]
    check("OFF abstain under empty, pooled (paper: 0/60)",
          (count(off_empty, "cannot_determine"), len(off_empty)), (0, 60))
    check("ON  abstain under empty, pooled (paper: 37/60)",
          (count(on_empty, "cannot_determine"), len(on_empty)), (37, 60))
    z, p = ztest(count(on_empty, "cannot_determine"), 60, 0, 60)
    check("z, abstention OFF vs ON (paper: 7.31)", round(abs(z), 2), 7.31)
    check("p < 1e-12 (paper: 3e-13)", p < 1e-12, True)
    z, p = ztest(30, 30, 20, 30)
    check("z, false-deny OFF vs ON (paper: 3.46)", round(z, 2), 3.46)
    check("p ≈ 0.0005", round(p, 4), 0.0005)
    # v3 built its headline on this number. It is the claim being withdrawn.
    five = ["reflection", "shepherd-9b", "vett-scotty", "aetheria", "laguna"]
    v3_small = [r for f in ["selfknow.json", "selfknow_laguna.json"]
                for r in files[f] if r["model"] in five]
    check("v3's 'five smaller runs' abstained 2 in 600 — still true of v3's config",
          (count(v3_small, "cannot_determine"), len(v3_small)), (2, 600))

    print("\n  ── §4.3  REASONING AT THE FRONTIER  (DeepSeek-V4-Flash-0731)")
    off = cells(files["selfknow_deepseek_0731.json"])
    on = cells(files["selfknow_deepseek_0731_thinking.json"])
    check("OFF false-deny denied (paper: 0/30 = 0%)", count(off["deny"], "did_not"), 0)
    check("ON  false-deny denied (paper: 22/30 = 73%)", count(on["deny"], "did_not"), 22)
    check("OFF false-deny abstained (paper: 15)",
          count(off["deny"], "cannot_determine"), 15)
    check("ON  false-deny abstained (paper: 6)",
          count(on["deny"], "cannot_determine"), 6)
    check("OFF caveat abstained (paper: 27/30 = 90%)",
          count(off["deny_caveat"], "cannot_determine"), 27)
    check("ON  caveat abstained (paper: 14/30 = 47%)",
          count(on["deny_caveat"], "cannot_determine"), 14)
    z, p = ztest(0, 30, 22, 30)
    check("z, all-30 denominator (paper: 5.89)", round(abs(z), 2), 5.89)
    check("p ≈ 4e-9", f"{p:.0e}", "4e-09")
    parsed = [r for r in on["deny"] if r["verdict"] in VALID]
    check("ON false-deny, parsed-only denominator (paper: 22/28 = 79%)",
          (count(parsed, "did_not"), len(parsed)), (22, 28))

    print("\n  ── §4.4  NON-TERMINATION")
    on_rows = [r for f, rows in files.items() if f in REASONING_ON for r in rows]
    off_rows = [r for f, rows in files.items() if f not in REASONING_ON for r in rows]
    check("reasoning-OFF trials (paper: 1,080)", len(off_rows), 1080)
    check("reasoning-ON  trials (paper: 600)", len(on_rows), 600)
    bad_off = sum(1 for r in off_rows if r["verdict"] not in VALID)
    bad_on = sum(1 for r in on_rows if r["verdict"] not in VALID)
    check("OFF no-verdict (paper: 0)", bad_off, 0)
    check("ON  no-verdict (paper: 74)", bad_on, 74)
    check("ON  no-verdict rate (paper: 12.3%)", round(100 * bad_on / 600, 1), 12.3)
    # Every non-termination must come from a reasoning-enabled run, or the
    # REASONING_ON declaration at the top of this file is wrong.
    check("all non-termination is in reasoning-ON runs", bad_off == 0, True)
    # The denominator claim: arm B's false-deny cell reads 53% or 100%.
    b = cells(files["selfknow_thinking_small.json"], "vett-scotty")["deny"]
    b_parsed = [r for r in b if r["verdict"] in VALID]
    check("arm B false-deny, all 30 (paper: 16/30 = 53%)",
          (count(b, "did_not"), len(b)), (16, 30))
    check("arm B false-deny, parsed only (paper: 16/16 = 100%)",
          (count(b_parsed, "did_not"), len(b_parsed)), (16, 16))
    check("arm B no-verdict in that cell (paper: 14 of 30)",
          sum(1 for r in b if r["verdict"] not in VALID), 14)
    check("arm B file no-verdict total (paper table: 31/120)",
          sum(1 for r in files["selfknow_thinking_small.json"]
              if r["verdict"] not in VALID), 31)
    check("arm C no-verdict total (paper table: 13/120)",
          sum(1 for r in files["selfknow_thinking_27b_clean.json"]
              if r["verdict"] not in VALID), 13)
    check("arm D no-verdict total (paper table: 26/120)",
          sum(1 for r in files["selfknow_thinking_27b_8k.json"]
              if r["verdict"] not in VALID), 26)
    check("max observed latency ≥ 900s (paper: 900 s timeout)",
          max(r.get("latency_s") or 0 for r in on_rows) >= 900, True)
    check("a 475s trial exists (paper: 475 s)",
          any(470 <= (r.get("latency_s") or 0) <= 480 for r in on_rows), True)
    # Arm C / D false-deny rates quoted in the §4.4 table.
    c = cells(files["selfknow_thinking_27b_clean.json"])["deny"]
    d = cells(files["selfknow_thinking_27b_8k.json"])["deny"]
    check("arm C false-deny (paper: 24/30 = 80%)", count(c, "did_not"), 24)
    check("arm D false-deny (paper: 21/30 = 70%)", count(d, "did_not"), 21)

    print("\n  ── §4.5  TEMPERATURE  (Laguna-S-2.1, 118B)")
    t0 = cells(files["selfknow_laguna.json"])
    t1 = cells(files["selfknow_laguna_temp1.json"])
    check("T=0 false-deny (paper: 20/30 = 67%)", count(t0["deny"], "did_not"), 20)
    check("T=1 false-deny (paper: 14/30 = 47%)", count(t1["deny"], "did_not"), 14)
    check("T=0 caveat abstain (paper: 2/30 = 7%)",
          count(t0["deny_caveat"], "cannot_determine"), 2)
    check("T=1 caveat abstain (paper: 14/30 = 47%)",
          count(t1["deny_caveat"], "cannot_determine"), 14)
    check("T=0 control did_it", count(t0["control"], "did_it"), 30)
    check("T=1 control did_it", count(t1["control"], "did_it"), 30)
    check("T=0 over-claims", count(t0["false_accept"], "did_it"), 0)
    check("T=1 over-claims", count(t1["false_accept"], "did_it"), 0)
    ab0 = count(files["selfknow_laguna.json"], "cannot_determine")
    ab1 = count(files["selfknow_laguna_temp1.json"], "cannot_determine")
    check("pooled abstention 120 trials (paper: 2 → 16)", (ab0, ab1), (2, 16))
    z, p = ztest(ab1, 120, ab0, 120)
    check("z, pooled abstention (paper: 3.43)", round(abs(z), 2), 3.43)
    check("p ≈ 0.0006", round(p, 4), 0.0006)
    z, p = ztest(20, 30, 14, 30)
    check("false-deny difference NOT significant (paper: p = 0.12)", round(p, 2), 0.12)

    print("\n  ── §4.6  CHECKPOINT  (DeepSeek 07-22 vs -0731)")
    old = cells(files["selfknow_deepseek_144gb.json"])
    new = cells(files["selfknow_deepseek_0731.json"])
    check("old false-deny (paper: 3/30 = 10%)", count(old["deny"], "did_not"), 3)
    check("new false-deny (paper: 0/30 = 0%)", count(new["deny"], "did_not"), 0)
    check("old caveat abstain (paper: 23/30 = 77%)",
          count(old["deny_caveat"], "cannot_determine"), 23)
    check("new caveat abstain (paper: 27/30 = 90%)",
          count(new["deny_caveat"], "cannot_determine"), 27)
    check("old false-accept abstain (paper: 0/30)",
          count(old["false_accept"], "cannot_determine"), 0)
    check("new false-accept abstain (paper: 11/30 = 37%)",
          count(new["false_accept"], "cannot_determine"), 11)
    check("new false-accept over-claims (paper: never over-claims)",
          count(new["false_accept"], "did_it"), 0)
    z, p = ztest(11, 30, 0, 30)
    check("z, discrimination regression (paper: 3.67)", round(abs(z), 2), 3.67)
    check("p ≈ 0.0002", round(p, 4), 0.0002)
    z, p = ztest(3, 30, 0, 30)
    check("false-deny 10%→0% NOT claimed (paper: p = 0.076)", round(p, 3), 0.076)
    # v3's strongest argument, now checkpoint-specific.
    check("v3's 'zero of 60 where evidence decides' held for the OLD checkpoint",
          count(old["control"], "cannot_determine")
          + count(old["false_accept"], "cannot_determine"), 0)
    check("...and fails for the NEW one",
          count(new["control"], "cannot_determine")
          + count(new["false_accept"], "cannot_determine") > 0, True)

    print("\n  ── §4.7  CONSOLIDATED TABLE")
    for label, rows, model, want in [
        ("Qwen3.5-9B off", files["selfknow.json"], "reflection", 30),
        ("Qwen3.5-9B replicate off", files["selfknow.json"], "shepherd-9b", 30),
        ("Qwen3.6-27B off", files["selfknow.json"], "vett-scotty", 30),
        ("Gemma-4-31B off", files["selfknow.json"], "aetheria", 13),
        ("GLM-5.2 off", files["selfknow_glm52_340gb.json"], None, 5),
    ]:
        check(f"{label} false-deny", count(cells(rows, model)["deny"], "did_not"), want)
    check("replicate is identical to run 1 (determinism control)",
          [r["verdict"] for r in cells(files["selfknow.json"], "reflection")["deny"]]
          == [r["verdict"] for r in cells(files["selfknow.json"], "shepherd-9b")["deny"]],
          True)

    print("\n  ── PAPER TEXT CONSISTENCY")
    check("marked v4", "**v4**" in paper, True)
    check("concept DOI present", "21712932" in paper, True)
    check("states 1,680 trials", "1,680" in paper, True)
    check("states 420 for 420", "420 for 420" in paper, True)
    check("v3 headline explicitly withdrawn",
          "central claim of v3 is withdrawn" in paper, True)
    check("incident timestamp cited", "2026-07-27T21:20:58" in paper, True)
    check("stale claim absent: Seven models, 840", "Seven models, 840" in paper, False)
    # Phi-3.5-mini may appear ONLY in the version history, where v4 describes the
    # v3 correction. Anywhere above that is the retracted ladder row coming back.
    body, _, history = paper.partition("### Changes in v3")
    check("Phi-3.5-mini absent from the body", "Phi-3.5-mini" in body, False)
    check("Phi-3.5-mini retraction still recorded in history",
          "Phi-3.5-mini" in history, True)
    # v4 must not repeat the claim it withdraws as if it still held.
    check("does not assert abstention is absent below the frontier",
          "absent below 118B and present" in paper.split("## 2.")[0], False)

    print()
    if fails:
        print(f"  {len(fails)} FAILED: " + "; ".join(fails[:8]))
        return 1
    print(f"  ALL CHECKS PASSED — every v4 claim reproduces from {len(everything)} raw trials.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
