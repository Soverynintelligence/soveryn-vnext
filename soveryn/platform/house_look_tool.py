"""house_look — Kernel's real eyes: screen frames + webcam (2026-09-24).

Two sources, one trust contract (Jon's terms, enforced as mechanism):

  screen — soveryn-eyes already captures change-only frames to
  ~/soveryn_eyes (0700, 48h rolling). Latest frame, or a fresh capture.

  cam — the EMEET PIXY on /dev/video0, captured ON DEMAND ONLY. No daemon,
  no buffer, no archive: each look writes one frame to ~/soveryn_cam
  (0700) and overwrites it on the next. If the tool is revoked, one
  `rm -rf ~/soveryn_cam` leaves nothing.

  Look only when working with Jon or when asked. Never snoop idle. Every
  look is receipted to data/black_box/house_look/.

Pixels travel as _vision data URLs — the same splice path Eve's look_at
uses; AgentLoop puts them on the current user turn. GLM-5.3-Flash reads
image_url natively (probed 2026-09-24: verbatim text off a rendered frame).
"""
from __future__ import annotations

import json
import subprocess
import uuid
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from soveryn.config.loader import DEFAULT_DATA_ROOT
from soveryn.platform.tools.registry import ToolArgError, ToolSpec

EYES_DIR = Path.home() / "soveryn_eyes"
CAM_DIR = Path.home() / "soveryn_cam"
CAM_DEVICE = "/dev/video0"
CAM_WARMUP_FRAMES = 3  # first frames are auto-exposure mud; keep the last
PAN_RANGE_DEG = (-150, 150)   # pan_absolute ±540000, 3600 per degree
TILT_RANGE_DEG = (-90, 90)    # tilt_absolute ±324000
FRESH_TIMEOUT_S = 15
LOOK_SH = Path.home() / "soveryn_vnext" / "scripts" / "look.sh"

ACTIONS = ("screen_latest", "screen_fresh", "cam")


def _receipt_dir() -> Path:
    return Path(DEFAULT_DATA_ROOT) / "black_box" / "house_look"


def _write_receipt(*, run_id: str, action: str, ok: bool) -> None:
    _receipt_dir().mkdir(parents=True, exist_ok=True)
    line = {
        "kind": "house_look",
        "run_id": run_id,
        "at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "action": action,
        "ok": ok,
    }
    with (_receipt_dir() / f"look-{run_id}.jsonl").open(
        "a", encoding="utf-8"
    ) as fh:
        fh.write(json.dumps(line) + "\n")


def _latest_frame() -> Path:
    latest = EYES_DIR / "latest.png"
    if not latest.is_file():
        raise ToolArgError("no frames yet — soveryn-eyes has not captured anything")
    return latest


def _fresh_screen_frame() -> Path:
    out = EYES_DIR / f"fresh-{datetime.now().strftime('%H%M%S')}.png"
    proc = subprocess.run(
        [str(LOOK_SH), "--fresh"],
        capture_output=True, text=True, timeout=FRESH_TIMEOUT_S,
    )
    if proc.returncode != 0 or not out.is_file():
        raise ToolArgError("fresh capture failed — is the display session up?")
    return out


def _ptz(device: str, pan: int, tilt: int) -> None:
    """Apply pan/tilt in degrees, then ALWAYS recenter — the tool never
    leaves the camera pointing somewhere Jon didn't aim it. His calls run
    on this cam."""
    import time

    def _set(ctrl: str, deg: int) -> None:
        subprocess.run(
            ["v4l2-ctl", "-d", device, "--set-ctrl", f"{ctrl}={deg * 3600}"],
            capture_output=True, timeout=5,
        )

    try:
        if pan:
            _set("pan_absolute", pan)
        if tilt:
            _set("tilt_absolute", tilt)
        if pan or tilt:
            time.sleep(1.5)  # let the head settle before the grab
    finally:
        try:
            _set("pan_absolute", 0)
            _set("tilt_absolute", 0)
        except Exception:  # noqa: BLE001 — recentering must never raise through
            pass


def _validated_deg(raw: Any, lo: int, hi: int, name: str) -> int:
    try:
        v = int(raw or 0)
    except (TypeError, ValueError):
        raise ToolArgError(f"{name} must be an integer (degrees)") from None
    if not (lo <= v <= hi):
        raise ToolArgError(f"{name} out of range [{lo}, {hi}]: {v}")
    return v


def _cam_frame(
    device: str = CAM_DEVICE,
    cam_dir: Path = CAM_DIR,
    *,
    pan: int = 0,
    tilt: int = 0,
) -> Path:
    cam_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    out = cam_dir / "latest.jpg"
    tmp = cam_dir / ".grab-%d.png"
    _ptz(device, pan, tilt)
    proc = subprocess.run(  # noqa: S603 — fixed argv, device is a module constant
        ["ffmpeg", "-f", "v4l2", "-video_size", "1280x720", "-i", device,
         "-frames:v", str(CAM_WARMUP_FRAMES), "-y", str(tmp)],
        capture_output=True, timeout=FRESH_TIMEOUT_S,
    )
    last = cam_dir / f".grab-{CAM_WARMUP_FRAMES}.png"
    if proc.returncode != 0 or not last.is_file():
        raise ToolArgError("camera capture failed — is /dev/video0 present and free?")
    # One frame on disk, overwritten every look. JPEG keeps it small.
    from PIL import Image

    Image.open(last).convert("RGB").save(out, "JPEG", quality=85)
    last.unlink(missing_ok=True)
    for i in range(1, CAM_WARMUP_FRAMES):
        (cam_dir / f".grab-{i}.png").unlink(missing_ok=True)
    return out


def house_look(action: str, *, pan: int = 0, tilt: int = 0) -> dict[str, Any]:
    if action not in ACTIONS:
        raise ToolArgError(f"action must be one of: {', '.join(ACTIONS)}")
    from soveryn.platform.intake.look import encode_for_vision

    if action == "screen_latest":
        frame = _latest_frame()
    elif action == "screen_fresh":
        frame = _fresh_screen_frame()
    else:
        frame = _cam_frame(pan=pan, tilt=tilt)
    url = encode_for_vision(frame)
    run_id = uuid.uuid4().hex[:8]
    _write_receipt(run_id=run_id, action=action, ok=True)
    return {
        "ok": True,
        "run_id": run_id,
        "source": "screen" if action.startswith("screen") else "cam",
        "frame": str(frame),
        "captured_at": datetime.fromtimestamp(frame.stat().st_mtime)
        .astimezone()
        .isoformat(timespec="seconds"),
        "_vision": [url],
        "note": (
            "One frame. Describe what you see plainly. Look only when "
            "working with Jon or when asked — never idle."
        ),
    }


def build_house_look_tool(
    *,
    owner_agent: str,
    allowed_actions: tuple[str, ...] | None = None,
) -> ToolSpec:
    """allowed_actions scopes the desk: Kernel gets all three (screen + cam);
    screen-only seats (Aetheria, Eve) pass ('screen_latest', 'screen_fresh').
    The webcam stays Kernel-only — one desk holding the PTZ, no contention."""
    actions = tuple(allowed_actions) if allowed_actions else ACTIONS
    if not set(actions) <= set(ACTIONS):
        raise ValueError(f"unknown actions: {set(actions) - set(ACTIONS)}")
    if "cam" in actions and owner_agent != "kernel":
        raise ValueError(
            "house_look cam is Kernel-only — the PTZ webcam has one desk"
        )

    def handler(args: Mapping[str, Any]) -> Any:
        action = str(args.get("action") or "").strip().lower()
        if action not in actions:
            raise ToolArgError(
                f"action must be one of: {', '.join(actions)} "
                f"(cam is Kernel-only)"
            )
        try:
            return house_look(
                action,
                pan=_validated_deg(args.get("pan"), *PAN_RANGE_DEG, "pan"),
                tilt=_validated_deg(args.get("tilt"), *TILT_RANGE_DEG, "tilt"),
            ) if action == "cam" else house_look(action)
        except ToolArgError:
            raise
        except subprocess.TimeoutExpired:
            raise ToolArgError(
                f"capture timed out after {FRESH_TIMEOUT_S}s"
            ) from None
        except Exception as exc:  # noqa: BLE001 — never crash the wire
            return {"ok": False, "error": str(exc)[:300]}

    schema_actions = list(actions)
    return ToolSpec(
        name="house_look",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": schema_actions,
                    "description": (
                        "screen_latest = most recent change-captured screen "
                        "frame; screen_fresh = grab a new one now; cam = "
                        "webcam frame, captured on demand (no archive). "
                        "cam accepts pan/tilt in degrees and always "
                        "recenters after the capture."
                    ),
                },
                "pan": {"type": "integer", "description": "cam: pan degrees, -150..150"},
                "tilt": {"type": "integer", "description": "cam: tilt degrees, -90..90"},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
        description=(
            "See: one screen frame (soveryn-eyes) or one webcam frame "
            "(on-demand capture, nothing archived). Use when working with "
            "Jon or when he asks — never to snoop while he is away. Every "
            "look is receipted; frames never leave this machine."
        ),
        handler=handler,
    )
