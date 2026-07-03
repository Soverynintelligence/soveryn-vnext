"""The search loop: run each candidate through the measurement primitive
(sequential — shared GPUs), rank by tok_s, pick the empirical winner. A candidate
that raises is recorded as load_failed and the search continues. Never fakes a
winner: winner is None when nothing came back ok.
"""
from __future__ import annotations
from dataclasses import dataclass

from soveryn.platform.tuner.candidate import Candidate
from soveryn.platform.tuner.result import Measurement
from soveryn.platform.tuner.measure import measure as _default_measure


@dataclass
class Ranked:
    candidate: Candidate
    measurement: Measurement


@dataclass
class SearchResult:
    ranked: list          # list[Ranked]: ok (tok_s desc) first, then failures
    winner: Candidate | None


def run_search(candidates, *, devices, measure_fn=_default_measure, on_progress=None) -> SearchResult:
    results: list[Ranked] = []
    for idx, cand in enumerate(candidates):
        if on_progress is not None:
            on_progress(idx, len(candidates), cand)
        try:
            m = measure_fn(cand, devices=devices)
        except Exception as exc:                       # a bad candidate must not kill the search
            m = Measurement(status="load_failed", detail=f"measure raised: {exc}")
        results.append(Ranked(candidate=cand, measurement=m))

    oks = [r for r in results if r.measurement.status == "ok"]
    fails = [r for r in results if r.measurement.status != "ok"]
    oks.sort(key=lambda r: (r.measurement.tok_s or 0.0), reverse=True)
    return SearchResult(ranked=oks + fails, winner=(oks[0].candidate if oks else None))
