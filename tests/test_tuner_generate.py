"""Generator tests — pure, no GPU."""
from soveryn.platform.tuner.generate import model_footprint


def test_model_footprint_sums_split_shards(tmp_path):
    for k in (1, 2, 3):
        (tmp_path / f"M-0000{k}-of-00003.gguf").write_bytes(b"x" * (10 * k))
    fp = model_footprint(str(tmp_path / "M-00001-of-00003.gguf"))
    assert fp == 10 + 20 + 30


def test_model_footprint_single_file(tmp_path):
    p = tmp_path / "solo.gguf"
    p.write_bytes(b"y" * 123)
    assert model_footprint(str(p)) == 123
