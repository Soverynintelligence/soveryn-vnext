from soveryn.platform.citizen_shapes import load_shapes, set_shape


def test_defaults_then_set(tmp_path, monkeypatch):
    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    mapping = load_shapes()
    assert mapping["aetheria"] == "round"
    assert mapping["kernel"] == "squircle"
    saved = set_shape("kernel", "bean")
    assert saved["shape"] == "bean"
    assert load_shapes()["kernel"] == "bean"
    assert set_shape("eve", "heart")["shape"] == "heart"
    assert set_shape("aetheria", "star")["shape"] == "star"
    assert set_shape("kernel", "moon")["shape"] == "moon"
    assert set_shape("eve", "blob")["shape"] == "blob"


def test_rejects_unknown_shape(tmp_path, monkeypatch):
    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    try:
        set_shape("eve", "radar")
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "shape" in str(exc)
