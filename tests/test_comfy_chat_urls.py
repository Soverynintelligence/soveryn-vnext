from __future__ import annotations

from pathlib import Path

from soveryn.app.comfy_chat_urls import comfy_urls_from_text


def test_extracts_backticked_eve_filenames():
    text = (
        "four looks at Eve's face sitting in `~/ComfyUI/output/`:\n"
        "1. **`eve_00001_.png`** — the base.\n"
        "2. **`eve_00002_.png`** — light-and-motion.\n"
    )
    assert comfy_urls_from_text(text, output_dir=Path("/nonexistent")) == [
        "/aetheria/img/eve_00001_.png",
        "/aetheria/img/eve_00002_.png",
    ]


def test_hash_ref_only_when_file_exists(tmp_path: Path):
    (tmp_path / "eve_00008_.png").write_bytes(b"x")
    (tmp_path / "eve_00001_.png").write_bytes(b"x")
    urls = comfy_urls_from_text(
        "So #8 is the *hot* one. I generated those with calm confidence.",
        output_dir=tmp_path,
    )
    assert urls == ["/aetheria/img/eve_00008_.png"]
    assert comfy_urls_from_text("So #9 is missing. I generated those.", output_dir=tmp_path) == []
    assert comfy_urls_from_text("**Spark #1** (10.10.10.2)", output_dir=tmp_path) == []
    assert comfy_urls_from_text("**CWG Receipt — Entry #1**", output_dir=tmp_path) == []
    assert comfy_urls_from_text(
        "That's actually still useful:\n- Right now **Spark #1**",
        output_dir=tmp_path,
    ) == []
