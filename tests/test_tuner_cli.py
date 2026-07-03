"""CLI formatting test — pure, no GPU."""
from soveryn.platform.tuner.candidate import Candidate
from soveryn.platform.tuner.result import Measurement
from soveryn.platform.tuner.search import Ranked, SearchResult
from soveryn.platform.tuner.__main__ import format_ranked_table


def _c(name, ot=None):
    return Candidate(model_file="/m.gguf", device_map=name, ngl=99, ctx_size=4096,
                     cache_type_k="f16", cache_type_v="f16", flash_attn=True, ot_offload=ot)


def test_table_flags_winner_and_shows_statuses():
    win = _c("CUDA0")
    res = SearchResult(
        ranked=[Ranked(win, Measurement(status="ok", tok_s=14.2)),
                Ranked(_c("CUDA1"), Measurement(status="oom"))],
        winner=win)
    out = format_ranked_table(res)
    assert "WINNER" in out
    assert "14.2 tok/s" in out
    assert "oom" in out


def test_table_reports_no_working_config():
    res = SearchResult(
        ranked=[Ranked(_c("CUDA0"), Measurement(status="oom"))], winner=None)
    out = format_ranked_table(res)
    assert "NO WORKING CONFIG" in out
