"""Generate the synthetic MPO fixtures for flatten-mpo.test.cjs.

Reproduces the layout that broke the 120-byte prefix check: a JFIF APP0, an
Exif APP1 larger than 2 KB, then the APP2 "MPF\\0" header, with no Apple
"AMPF" marker. Two tiny 8x8 frames. Also writes a single-frame JPEG with the
same large Exif and no MPF, which must be left alone.

    python packages/soveryn-cli/test/make-mpo-fixture.py
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

OUT = Path(__file__).resolve().parent / "fixtures"


def _exif() -> bytes:
    ex = Image.Exif()
    ex[0x010E] = "synthetic MPO fixture " + "x" * 2400  # ImageDescription: APP1 > 2 KB
    return ex.tobytes()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    picture = Image.new("RGB", (8, 8), (200, 40, 40))
    depth = Image.new("L", (8, 8), 128).convert("RGB")

    mpo = io.BytesIO()
    picture.save(
        mpo, "MPO", save_all=True, append_images=[depth], exif=_exif(), quality=60
    )
    data = mpo.getvalue()
    assert data.find(b"AMPF") == -1, "fixture must not carry Apple AMPF"
    assert data.find(b"MPF\x00") > 2048, "MPF must sit past the 2 KB Exif"
    (OUT / "synthetic-mpo.jpg").write_bytes(data)

    flat = io.BytesIO()
    picture.save(flat, "JPEG", exif=_exif(), quality=60)
    assert b"MPF\x00" not in flat.getvalue()
    (OUT / "synthetic-flat.jpg").write_bytes(flat.getvalue())


if __name__ == "__main__":
    main()
