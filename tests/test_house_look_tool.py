"""house_look tests — screen frames + on-demand webcam for Kernel.

Pins the trust contract: on-demand only (cam keeps no archive beyond the
overwritten latest.jpg), pan/tilt always recenter, receipts every look,
and the _vision splice payload is present so pixels actually reach the
model turn.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from PIL import Image

from soveryn.platform.house_look_tool import (
    ACTIONS,
    _validated_deg,
    build_house_look_tool,
    house_look,
)
from soveryn.platform.tools.registry import ToolArgError

REPO = Path(__file__).resolve().parents[1]


def _fake_eyes(tmp_path: Path) -> Path:
    eyes = tmp_path / "soveryn_eyes"
    eyes.mkdir()
    Image.new("RGB", (320, 180), "#222").save(eyes / "latest.png")
    return eyes


def test_screen_latest_returns_vision_payload(tmp_path, monkeypatch):
    monkeypatch.setattr("soveryn.platform.house_look_tool.EYES_DIR", _fake_eyes(tmp_path))
    r = house_look("screen_latest")
    assert r["ok"] is True and r["source"] == "screen"
    assert len(r["_vision"]) == 1 and r["_vision"][0].startswith("data:image/")


def test_screen_latest_without_frames_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "soveryn.platform.house_look_tool.EYES_DIR", tmp_path / "empty"
    )
    with pytest.raises(ToolArgError):
        house_look("screen_latest")


def test_cam_recenters_and_captures(tmp_path, monkeypatch):
    """Real PTZ capture if the cam is present; always asserts recenter."""
    if not Path("/dev/video0").exists():
        pytest.skip("no webcam on this host")
    sets: list[str] = []
    real_run = __import__("subprocess").run

    def spy_run(argv, **kw):
        if argv[:2] == ["v4l2-ctl", "-d"] and "--set-ctrl" in argv:
            sets.append(argv[-1])
        return real_run(argv, **kw)

    monkeypatch.setattr("soveryn.platform.house_look_tool.subprocess.run", spy_run)
    monkeypatch.setattr(
        "soveryn.platform.house_look_tool.CAM_DIR", tmp_path / "cam"
    )
    r = house_look("cam", pan=45, tilt=-10)
    assert r["ok"] is True and r["source"] == "cam"
    assert r["_vision"] and r["frame"].endswith("latest.jpg")
    pan_sets = [s for s in sets if s.startswith("pan_absolute=")]
    assert pan_sets[-2:] == ["pan_absolute=162000", "pan_absolute=0"], (
        f"camera must recenter after the capture, saw: {pan_sets}"
    )


def test_pan_tilt_range_validation():
    with pytest.raises(ToolArgError):
        _validated_deg(500, -150, 150, "pan")
    with pytest.raises(ToolArgError):
        _validated_deg("left", -150, 150, "pan")
    assert _validated_deg(None, -150, 150, "pan") == 0


def test_every_look_is_receipted(tmp_path, monkeypatch):
    monkeypatch.setattr("soveryn.platform.house_look_tool.EYES_DIR", _fake_eyes(tmp_path))
    monkeypatch.setattr(
        "soveryn.platform.house_look_tool._receipt_dir", lambda: tmp_path / "bb"
    )
    house_look("screen_latest")
    receipts = list((tmp_path / "bb").glob("look-*.jsonl"))
    assert len(receipts) == 1
    assert "house_look" in receipts[0].read_text()


def test_bad_action_rejected():
    with pytest.raises(ToolArgError):
        house_look("browse_archive")  # no buffer paging, by design
    assert set(ACTIONS) == {"screen_latest", "screen_fresh", "cam"}
