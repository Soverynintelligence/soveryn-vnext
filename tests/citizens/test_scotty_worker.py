"""Scotty worker desk touch (presence half of residence)."""
from pathlib import Path

from soveryn.citizens import scotty_worker


def test_touch_desk_writes_alive_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(scotty_worker, "DESK", tmp_path / "scotty")
    scotty_worker.touch_desk()
    alive = tmp_path / "scotty" / "notes" / "worker_alive"
    assert alive.is_file()
    text = alive.read_text(encoding="utf-8")
    assert "scotty worker alive" in text
    assert (tmp_path / "scotty" / "inbox").is_dir()
