"""Search-loop tests — fake measure_fn, no GPU."""
from soveryn.platform.tuner.candidate import Candidate
from soveryn.platform.tuner.result import Measurement
from soveryn.platform.tuner.search import run_search


def _c(name):
    return Candidate(model_file="/m.gguf", device_map=name, ngl=99, ctx_size=4096,
                     cache_type_k="f16", cache_type_v="f16", flash_attn=True)


def test_winner_is_highest_tok_s_among_ok():
    cands = [_c("CUDA0"), _c("CUDA1"), _c("CUDA2")]
    table = {"CUDA0": Measurement(status="ok", tok_s=9.0),
             "CUDA1": Measurement(status="oom"),
             "CUDA2": Measurement(status="ok", tok_s=14.0)}
    res = run_search(cands, devices=[0, 1, 2],
                     measure_fn=lambda c, *, devices: table[c.device_map])
    assert res.winner.device_map == "CUDA2"
    assert res.ranked[0].candidate.device_map == "CUDA2"     # ok, sorted desc
    assert res.ranked[-1].measurement.status == "oom"        # failures last


def test_no_ok_means_no_winner():
    cands = [_c("CUDA0"), _c("CUDA1")]
    res = run_search(cands, devices=[0, 1],
                     measure_fn=lambda c, *, devices: Measurement(status="oom"))
    assert res.winner is None


def test_raising_candidate_is_recorded_and_search_continues():
    cands = [_c("BAD"), _c("CUDA0")]

    def flaky(c, *, devices):
        if c.device_map == "BAD":
            raise RuntimeError("boom")
        return Measurement(status="ok", tok_s=5.0)

    res = run_search(cands, devices=[0], measure_fn=flaky)
    assert res.winner.device_map == "CUDA0"                  # search survived the raise
    bad = [r for r in res.ranked if r.candidate.device_map == "BAD"][0]
    assert bad.measurement.status == "load_failed"
    assert "boom" in bad.measurement.detail


def test_on_progress_called_per_candidate():
    cands = [_c("CUDA0"), _c("CUDA1")]
    seen = []
    run_search(cands, devices=[0, 1],
               measure_fn=lambda c, *, devices: Measurement(status="ok", tok_s=1.0),
               on_progress=lambda i, n, c: seen.append((i, n, c.device_map)))
    assert seen == [(0, 2, "CUDA0"), (1, 2, "CUDA1")]
