"""autotune CLI: python -m soveryn.platform.tuner <model_file>

Probe the rig, generate a candidate spread, measure each, print a ranked table.
Reports the winning config; does NOT auto-apply it to the router.
"""
from __future__ import annotations
import sys

from soveryn.platform.tuner.rig import probe_rig
from soveryn.platform.tuner.generate import generate_candidates, model_footprint
from soveryn.platform.tuner.search import run_search, SearchResult


def format_ranked_table(result: SearchResult) -> str:
    lines = []
    for r in result.ranked:
        c, m = r.candidate, r.measurement
        tag = "WINNER" if c is result.winner else "      "
        speed = f"{m.tok_s:.1f} tok/s" if (m.status == "ok" and m.tok_s) else m.status
        lines.append(f"{tag}  {c.device_map:<18} ot={c.ot_offload or '-':<9} "
                     f"kv={c.cache_type_k:<5} -> {speed}")
    if result.winner is None:
        lines.append("NO WORKING CONFIG — nothing ran ok (see statuses above)")
    return "\n".join(lines)


def _progress(i: int, n: int, cand) -> None:
    print(f"[{i + 1}/{n}] measuring {cand.backend}: {cand.device_map} "
          f"ot={cand.ot_offload or '-'} kv={cand.cache_type_k} …", flush=True)


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("usage: python -m soveryn.platform.tuner <model_file>", file=sys.stderr)
        return 2
    model_file = argv[0]
    rig = probe_rig()
    fp = model_footprint(model_file)
    print(f"model footprint: {fp / 1e9:.1f} GB | devices: {len(rig.devices)} | "
          f"RAM: {rig.total_ram_bytes / 1e9:.0f} GB", flush=True)
    cands = generate_candidates(model_file, rig)
    print(f"generated {len(cands)} candidates; measuring sequentially (blocking)…", flush=True)
    result = run_search(cands, devices=[d.index for d in rig.devices], on_progress=_progress)
    print(format_ranked_table(result))
    return 0 if result.winner else 1


if __name__ == "__main__":
    raise SystemExit(main())
