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


from soveryn.platform.tuner.generate import generate_candidates
from soveryn.platform.tuner.rig import Rig, Device

GB = 1024 ** 3


def _rig3():
    return Rig(devices=(
        Device(0, "cuda", "Blackwell", 48 * GB, "0000:45:00.0"),
        Device(1, "cuda", "Quadro-A", 48 * GB, "0000:01:00.0"),
        Device(2, "cuda", "Quadro-B", 48 * GB, "0000:81:00.0"),
    ), total_ram_bytes=256 * GB)


def _write_model(tmp_path, gb):
    p = tmp_path / "m.gguf"
    p.write_bytes(b"\0")           # tiny file; footprint is monkeypatched below
    return str(p)


def test_generate_empty_rig_returns_empty(tmp_path):
    # a rig with no devices yields no candidates (total function — never a phantom --device "" launch)
    empty = Rig(devices=(), total_ram_bytes=256 * GB)
    assert generate_candidates(_write_model(tmp_path, 10), empty) == []


def test_generate_spread_for_fitting_model(tmp_path, monkeypatch):
    import soveryn.platform.tuner.generate as g
    monkeypatch.setattr(g, "model_footprint", lambda _f: 10 * GB)  # fits everything
    cands = generate_candidates(_write_model(tmp_path, 10), _rig3())
    assert len(cands) <= 6
    # always-include big-model paths survive the cap:
    assert any(c.ot_offload == "exps=CPU" for c in cands)
    assert any(c.cache_type_k == "q8_0" for c in cands)
    # topology-relevant single-device option is measured (Blackwell alone):
    assert any(c.device_map == "CUDA0" for c in cands)
    # every candidate is backend-consistent (cuda device names):
    assert all(c.backend == "cuda" and c.device_map.startswith("CUDA") for c in cands)


def test_generate_big_model_still_emits_offload(tmp_path, monkeypatch):
    import soveryn.platform.tuner.generate as g
    monkeypatch.setattr(g, "model_footprint", lambda _f: 400 * GB)  # fits nothing
    cands = generate_candidates(_write_model(tmp_path, 400), _rig3())
    assert any(c.ot_offload == "exps=CPU" for c in cands)   # the path that can actually run it
    assert all(c.device_map == "CUDA0,CUDA1,CUDA2" for c in cands)  # no fitting subset exists


def test_generator_ignores_pci_bus_id(tmp_path, monkeypatch):
    import soveryn.platform.tuner.generate as g
    monkeypatch.setattr(g, "model_footprint", lambda _f: 10 * GB)
    r1 = _rig3()
    r2 = Rig(devices=tuple(
        Device(d.index, d.backend, d.name, d.vram_bytes, "9999:99:99.9") for d in r1.devices
    ), total_ram_bytes=r1.total_ram_bytes)
    mf = _write_model(tmp_path, 10)
    assert generate_candidates(mf, r1) == generate_candidates(mf, r2)  # bus IDs must not change output
