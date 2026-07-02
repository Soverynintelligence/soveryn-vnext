"""Real-rig self-test — deliberately triggers each failure class on THIS rack.

Run:  systemctl --user stop soveryn.target   (free VRAM)
      pytest tests/test_tuner_measure_rig.py -m rig -v
This is the hardening deliverable: proof the primitive classifies the rig's
actual failures, not just fixture strings.
"""
import pytest
from soveryn.platform.tuner.candidate import Candidate
from soveryn.platform.tuner.measure import measure

pytestmark = pytest.mark.rig
SMALL = "/mnt/soveryn_models/GGUF/gemma-4-E4B-it-Q8_0.gguf"
BIG = "/mnt/soveryn_models/GGUF/google_gemma-4-31B-it-Q8_0.gguf"
DEVS = [0, 1, 2]   # monitor all — mapping is uncertain, teardown check is baseline-relative

def _c(**kw):
    base = dict(model_file=SMALL, device_map="CUDA0", ngl=99, ctx_size=2048,
                cache_type_k="q8_0", cache_type_v="q8_0", flash_attn=True)
    base.update(kw); return Candidate(**base)

def test_ok_and_teardown_returns_to_baseline():
    m = measure(_c(), devices=DEVS)
    assert m.status == "ok", f"expected ok, got {m.status}: {m.detail}"
    assert m.tok_s and m.tok_s > 0
    # teardown proof: a second run isn't false-OOM'd by leaked VRAM
    m2 = measure(_c(), devices=DEVS)
    assert m2.status == "ok", f"second run: {m2.status}: {m2.detail}"

def test_oom_or_loadfail_by_absurd_context():
    m = measure(_c(ctx_size=4_000_000), devices=DEVS)
    assert m.status in ("oom", "load_failed"), f"got {m.status}: {m.detail}"

def test_load_failed_bad_model_path():
    m = measure(_c(model_file="/does/not/exist.gguf"), devices=DEVS)
    assert m.status == "load_failed", f"got {m.status}: {m.detail}"

def test_hung_by_tiny_load_timeout():
    m = measure(_c(model_file=BIG), devices=DEVS, load_timeout=2)
    assert m.status == "hung", f"got {m.status}: {m.detail}"
