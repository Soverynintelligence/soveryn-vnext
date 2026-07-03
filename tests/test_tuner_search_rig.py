"""End-to-end tuner self-test on the ACTUAL rack. Fleet must be DOWN.

Run: pytest tests/test_tuner_search_rig.py -m rig -v
Proves the whole loop: probe -> generate -> measure each -> pick a real winner.
"""
import os
import pytest

from soveryn.platform.tuner.rig import probe_rig
from soveryn.platform.tuner.generate import generate_candidates
from soveryn.platform.tuner.search import run_search

SMALL = "/mnt/soveryn_models/GGUF/gemma-4-E4B-it-Q8_0.gguf"


@pytest.mark.rig
def test_autotune_picks_a_real_winner_on_small_model():
    assert os.path.exists(SMALL), f"expected small test model at {SMALL}"
    rig = probe_rig()
    assert len(rig.devices) >= 1
    cands = generate_candidates(SMALL, rig)
    assert cands, "generator produced no candidates for a small model"
    result = run_search(cands, devices=[d.index for d in rig.devices])
    assert result.winner is not None, "no config ran ok on the real rig"
    win = [r for r in result.ranked if r.candidate is result.winner][0]
    assert win.measurement.status == "ok"
    assert (win.measurement.tok_s or 0) > 0
