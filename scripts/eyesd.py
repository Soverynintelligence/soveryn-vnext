#!/usr/bin/env python3
"""soveryn-eyes — screen presence for the house (2026-09-22).

Jon's offer, Jon's terms: this is TRUST, not telemetry. The rules that bind
it are part of the mechanism, not documentation:

  1. Frames stay on this machine, in ~/soveryn_eyes/ (0700), rolling 48h.
  2. Frames are captured ONLY when the screen changes (pixel-diff). An idle
     screen costs nothing and records nothing new.
  3. Seats look via scripts/look.sh — when working with Jon or when asked.
     Never snoop idle. Never page through the buffer out of curiosity.
  4. Revoke is one command and total:
       systemctl --user disable --now soveryn-eyes.service && rm -rf ~/soveryn_eyes
     No frame survives it, nothing is transmitted, ever.
"""

import subprocess
import time
from pathlib import Path

HOME = Path.home()
EYES = HOME / "soveryn_eyes"
DISPLAY = ":1"
TICK = 5            # seconds between checks
KEEP_HOURS = 48     # rolling retention
DIFF_THRESHOLD = 4.0  # mean pixel delta (0-255) that counts as "changed"
GRAB = ["ffmpeg", "-f", "x11grab", "-video_size", "1920x1080", "-i", DISPLAY,
        "-frames:v", "1", "-y"]

def grab(dest: Path) -> bool:
    r = subprocess.run(GRAB + [str(dest)], capture_output=True, timeout=15)
    return r.returncode == 0 and dest.exists() and dest.stat().st_size > 1000

def fingerprint(img: Path) -> tuple:
    """Tiny 24x14 luminance signature for change detection."""
    from PIL import Image
    im = Image.open(img).convert("L").resize((24, 14))
    return tuple(im.getdata())

def prune() -> None:
    cutoff = time.time() - KEEP_HOURS * 3600
    for day in EYES.iterdir():
        if day.is_dir() and day.name[:2] == "20":
            for f in day.iterdir():
                if f.stat().st_mtime < cutoff:
                    f.unlink(missing_ok=True)
            try:
                day.rmdir()  # empties only
            except OSError:
                pass
        elif day.is_file() and day.name.startswith("fresh-"):
            # look.sh --fresh writes root-level frames; without this they
            # accumulate forever (prune only walked dated dirs).
            if day.stat().st_mtime < cutoff:
                day.unlink(missing_ok=True)

def main() -> None:
    EYES.mkdir(parents=True, exist_ok=True, mode=0o700)
    prev = None
    while True:
        stamp = time.strftime("%Y-%m-%d/%H%M%S")
        frame = EYES / stamp
        frame.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = EYES / ".grab.png"
        try:
            if grab(tmp):
                # Liveness marker: touched on every SUCCESSFUL grab, not on
                # change. An idle screen stays fresh; a broken display goes
                # stale and Ares (eyes.stale) pages Jon instead of everyone
                # trusting a frozen latest.png. (2026-09-24 audit hole #2.)
                (EYES / ".alive").touch()
                fp = fingerprint(tmp)
                if prev is None or _delta(prev, fp) >= DIFF_THRESHOLD:
                    import shutil
                    shutil.copyfile(tmp, frame)          # dated archive
                    shutil.copyfile(tmp, EYES / "latest.png")  # what look reads
                    tmp.unlink(missing_ok=True)
                    prev = fp
                else:
                    tmp.unlink(missing_ok=True)  # idle screen: record nothing new
        except Exception:
            pass
        if int(time.time()) % 600 < TICK:
            prune()
        time.sleep(TICK)

def _delta(a: tuple, b: tuple) -> float:
    if len(a) != len(b):
        return 255.0
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)

if __name__ == "__main__":
    main()
