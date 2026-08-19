"""Aetheria's `generate_image` tool — wraps ComfyUI's API.

ComfyUI listens on :8188 when running (soveryn-comfyui.service). As of
2026-08-17 it is **on-demand**: this tool starts the unit (Quadro 0 GPU),
runs the gen, then stops the unit so Kernel keeps Quadro headroom.

Workflow: minimal SDXL Lightning JSON → POST /prompt → poll /history.

Defaults to JuggernautXL Lightning (6-step). Falls back to vanilla SDXL
if Lightning is missing. Output: ~/ComfyUI/output/.
"""
from __future__ import annotations

import json
import logging
import subprocess
import time
import urllib.parse
import urllib.request
import urllib.error
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from soveryn.platform.tools.registry import ToolArgError, ToolSpec

log = logging.getLogger(__name__)

DEFAULT_COMFYUI_URL = "http://127.0.0.1:8188"
DEFAULT_CHECKPOINT = "juggernautXL_v9Rdphoto2Lightning.safetensors"
FALLBACK_CHECKPOINT = "sd_xl_base_1.0.safetensors"
DEFAULT_OUTPUT_DIR = Path.home() / "ComfyUI" / "output"
COMFY_SYSTEMD_UNIT = "soveryn-comfyui.service"
# Cold start (systemd + torch) + Lightning gen; keep under agent patience.
COMFY_READY_TIMEOUT_SECONDS = 90.0
COMFY_POLL_TIMEOUT_SECONDS = 300.0

# Lightning checkpoints want few steps + low CFG + dpmpp_sde sampler
LIGHTNING_DEFAULTS = {
    "steps": 6,
    "cfg": 1.8,
    "sampler_name": "dpmpp_sde",
    "scheduler": "sgm_uniform",
}

# Vanilla SDXL fallback
VANILLA_DEFAULTS = {
    "steps": 28,
    "cfg": 7.0,
    "sampler_name": "dpmpp_2m",
    "scheduler": "karras",
}


def _build_workflow(
    *,
    checkpoint: str,
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    seed: int,
    steps: int,
    cfg: float,
    sampler_name: str,
    scheduler: str,
) -> dict[str, Any]:
    """Build the workflow JSON ComfyUI's API expects.

    Node IDs are arbitrary strings; we use stable numeric ones for
    readability. Each node has class_type + inputs; inputs can reference
    other nodes' outputs as `[node_id, output_index]`.
    """
    return {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": checkpoint},
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt, "clip": ["1", 1]},
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative_prompt, "clip": ["1", 1]},
        },
        "4": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": sampler_name,
                "scheduler": scheduler,
                "denoise": 1.0,
                "model": ["1", 0],
                "positive": ["2", 0],
                "negative": ["3", 0],
                "latent_image": ["4", 0],
            },
        },
        "6": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["5", 0], "vae": ["1", 2]},
        },
        "7": {
            "class_type": "SaveImage",
            "inputs": {
                "filename_prefix": "aetheria",
                "images": ["6", 0],
            },
        },
    }


def _http_post_json(url: str, body: dict, timeout: float = 30.0) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_get_json(url: str, timeout: float = 10.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _list_available_checkpoints(comfyui_url: str) -> list[str]:
    """Return the list of installed checkpoints from ComfyUI's object_info."""
    try:
        info = _http_get_json(
            f"{comfyui_url}/object_info/CheckpointLoaderSimple",
            timeout=5.0,
        )
        # Shape: { "CheckpointLoaderSimple": { "input": { "required": {
        #   "ckpt_name": [ [list of names], { ... } ] } } } }
        names = info["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]
        return list(names)
    except (urllib.error.URLError, KeyError, json.JSONDecodeError):
        return []


def _resolve_checkpoint(comfyui_url: str, requested: str | None) -> str:
    """Pick a usable checkpoint. Honor explicit request if it's installed;
    otherwise prefer Lightning, then vanilla SDXL."""
    available = _list_available_checkpoints(comfyui_url)
    if requested and requested in available:
        return requested
    if DEFAULT_CHECKPOINT in available:
        return DEFAULT_CHECKPOINT
    if FALLBACK_CHECKPOINT in available:
        return FALLBACK_CHECKPOINT
    if available:
        return available[0]  # something is better than nothing
    raise ToolArgError(
        "ComfyUI has no checkpoints installed at "
        "~/ComfyUI/models/checkpoints/"
    )


def _is_lightning_checkpoint(name: str) -> bool:
    """Heuristic — Lightning checkpoints want different defaults."""
    lower = name.lower()
    return "lightning" in lower or "lcm" in lower or "turbo" in lower


def _comfy_reachable(comfyui_url: str) -> bool:
    try:
        _http_get_json(f"{comfyui_url}/system_stats", timeout=2.0)
        return True
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return False


def _systemctl_user(*args: str, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["systemctl", "--user", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _ensure_comfy_running(comfyui_url: str) -> bool:
    """Start soveryn-comfyui if needed. Returns True if this call started it
    (caller should stop when done). Returns False if it was already up."""
    if _comfy_reachable(comfyui_url):
        return False
    log.info("ComfyUI down — starting %s (on-demand Quadro)", COMFY_SYSTEMD_UNIT)
    started = _systemctl_user("start", COMFY_SYSTEMD_UNIT, timeout=30.0)
    if started.returncode != 0:
        raise ToolArgError(
            f"failed to start {COMFY_SYSTEMD_UNIT}: "
            f"{(started.stderr or started.stdout or '').strip()[:400]}"
        )
    deadline = time.monotonic() + COMFY_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if _comfy_reachable(comfyui_url):
            return True
        time.sleep(1.0)
    raise ToolArgError(
        f"ComfyUI did not become ready within {COMFY_READY_TIMEOUT_SECONDS:.0f}s "
        f"after starting {COMFY_SYSTEMD_UNIT}"
    )


def _stop_comfy() -> None:
    """Best-effort stop — free Quadro VRAM for Kernel."""
    try:
        stopped = _systemctl_user("stop", COMFY_SYSTEMD_UNIT, timeout=60.0)
        if stopped.returncode != 0:
            log.warning(
                "ComfyUI stop returned %s: %s",
                stopped.returncode,
                (stopped.stderr or stopped.stdout or "").strip()[:300],
            )
        else:
            log.info("ComfyUI stopped (on-demand teardown)")
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning("ComfyUI stop failed: %s", e)


def _poll_until_complete(
    comfyui_url: str,
    prompt_id: str,
    *,
    timeout_seconds: float = COMFY_POLL_TIMEOUT_SECONDS,
    poll_interval: float = 1.0,
) -> dict:
    """Poll /history/<prompt_id> until the job appears. Returns the history
    entry for our prompt."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            history = _http_get_json(
                f"{comfyui_url}/history/{prompt_id}", timeout=5.0,
            )
            if prompt_id in history:
                return history[prompt_id]
        except urllib.error.URLError:
            pass
        time.sleep(poll_interval)
    raise ToolArgError(
        f"ComfyUI generation timed out after {timeout_seconds}s for prompt_id={prompt_id}"
    )


def _extract_image_paths(history_entry: dict) -> list[Path]:
    """Pull output image file paths from a completed history entry."""
    outputs = history_entry.get("outputs", {})
    paths: list[Path] = []
    for node_outputs in outputs.values():
        for image in node_outputs.get("images", []):
            filename = image.get("filename")
            subfolder = image.get("subfolder", "")
            image_type = image.get("type", "output")
            if not filename:
                continue
            if image_type == "output":
                base = DEFAULT_OUTPUT_DIR
            else:
                # input/ temp/ etc. — same layout but different subdir
                base = Path.home() / "ComfyUI" / image_type
            if subfolder:
                paths.append(base / subfolder / filename)
            else:
                paths.append(base / filename)
    return paths


def _path_to_chat_url(path: Path) -> str | None:
    """If `path` lives in ComfyUI's output dir AND has a UI-safe filename,
    return the vnext URL the chat UI uses to render it inline. Returns
    None for files outside the output dir (e.g., type='temp' or 'input').
    """
    try:
        rel = path.relative_to(DEFAULT_OUTPUT_DIR)
    except ValueError:
        return None
    # Only flat filenames — subfolder content is reachable via the file
    # path but the chat UI route doesn't currently handle subfolders.
    if rel.parent != Path("."):
        return None
    return f"/aetheria/img/{rel.name}"


def build_generate_image_tool(
    *,
    comfyui_url: str = DEFAULT_COMFYUI_URL,
) -> ToolSpec:
    """Aetheria's text-to-image tool. Owned by aetheria.

    Returns the local file path(s) of generated images. v1 is sync —
    Aetheria's chat turn blocks until generation completes (typically
    5-30s depending on checkpoint + steps).
    """

    def handler(args: Mapping[str, Any]) -> dict:
        prompt = str(args.get("prompt", "")).strip()
        if not prompt:
            raise ToolArgError("prompt must be a non-empty string")
        negative_prompt = str(args.get("negative_prompt", "blurry, low quality")).strip()
        width = int(args.get("width", 1024))
        height = int(args.get("height", 1024))
        if not (256 <= width <= 2048) or not (256 <= height <= 2048):
            raise ToolArgError("width and height must be between 256 and 2048")
        # ComfyUI wants multiples of 64 for SDXL
        width = (width // 64) * 64
        height = (height // 64) * 64
        seed_raw = args.get("seed")
        seed = int(seed_raw) if seed_raw is not None else int(uuid.uuid4().int & 0xFFFF_FFFF_FFFF_FFFF)

        # On-demand: spin Quadro Comfy only for this gen, then tear down.
        started_here = False
        try:
            started_here = _ensure_comfy_running(comfyui_url)

            requested_checkpoint = args.get("checkpoint")
            checkpoint = _resolve_checkpoint(comfyui_url, requested_checkpoint)
            # Pick defaults based on whether it's a Lightning variant
            defaults = LIGHTNING_DEFAULTS if _is_lightning_checkpoint(checkpoint) else VANILLA_DEFAULTS
            steps = int(args.get("steps", defaults["steps"]))
            cfg = float(args.get("cfg", defaults["cfg"]))
            sampler_name = str(args.get("sampler_name", defaults["sampler_name"]))
            scheduler = str(args.get("scheduler", defaults["scheduler"]))

            workflow = _build_workflow(
                checkpoint=checkpoint,
                prompt=prompt,
                negative_prompt=negative_prompt,
                width=width, height=height,
                seed=seed, steps=steps, cfg=cfg,
                sampler_name=sampler_name, scheduler=scheduler,
            )

            client_id = str(uuid.uuid4())
            try:
                queued = _http_post_json(
                    f"{comfyui_url}/prompt",
                    {"prompt": workflow, "client_id": client_id},
                    timeout=15.0,
                )
            except urllib.error.URLError as e:
                return {
                    "error": "comfyui_unreachable",
                    "message": f"could not reach ComfyUI at {comfyui_url}: {e}",
                }
            prompt_id = queued.get("prompt_id")
            if not prompt_id:
                return {
                    "error": "comfyui_rejected",
                    "message": f"ComfyUI did not return a prompt_id: {queued}",
                }
            node_errors = queued.get("node_errors", {})
            if node_errors:
                return {
                    "error": "comfyui_workflow_error",
                    "message": "ComfyUI flagged workflow errors",
                    "node_errors": node_errors,
                }

            history_entry = _poll_until_complete(comfyui_url, prompt_id)
            image_paths = _extract_image_paths(history_entry)
            if not image_paths:
                return {
                    "error": "no_images_returned",
                    "message": "Generation completed but no output images were recorded",
                    "prompt_id": prompt_id,
                }

            image_urls = [_path_to_chat_url(p) for p in image_paths]
            # Pair (path, url) results so callers can pick whichever they need.
            # The chat UI auto-renders any `/aetheria/img/...` URL it sees in
            # assistant content, so Aetheria should include the URL in her
            # natural-language response.
            return {
                "images": [str(p) for p in image_paths],
                "urls": [u for u in image_urls if u is not None],
                "count": len(image_paths),
                "checkpoint": checkpoint,
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "prompt_id": prompt_id,
                "comfy_on_demand": started_here,
            }
        finally:
            if started_here:
                _stop_comfy()

    return ToolSpec(
        name="generate_image",
        owner="aetheria",
        description=(
            "Generate an image from a text prompt via ComfyUI (on-demand GPU: "
            "starts Quadro Comfy for this call, then stops so Kernel keeps "
            "VRAM). Defaults to JuggernautXL Lightning (~5–15s once warm; "
            "cold start adds a bit). Returns file path + UI URL "
            "(`/aetheria/img/<filename>`). Include the URL inline in your "
            "reply — the chat UI auto-renders it."
        ),
        schema={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Positive prompt describing what to generate.",
                },
                "negative_prompt": {
                    "type": "string",
                    "description": "Optional negative prompt. Default: 'blurry, low quality'.",
                },
                "width": {
                    "type": "integer",
                    "minimum": 256,
                    "maximum": 2048,
                    "description": "Image width in pixels (snapped to multiple of 64). Default 1024.",
                },
                "height": {
                    "type": "integer",
                    "minimum": 256,
                    "maximum": 2048,
                    "description": "Image height in pixels (snapped to multiple of 64). Default 1024.",
                },
                "seed": {
                    "type": "integer",
                    "description": "Random seed. Omit for a fresh random seed each call.",
                },
                "steps": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "description": (
                        "Diffusion steps. Default 6 for Lightning checkpoints, 28 for vanilla."
                    ),
                },
                "cfg": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 30.0,
                    "description": (
                        "Classifier-free guidance scale. Default 1.8 for Lightning, 7.0 for vanilla."
                    ),
                },
                "checkpoint": {
                    "type": "string",
                    "description": (
                        "Override the default checkpoint. Falls back to a Lightning variant "
                        "if available, then vanilla SDXL."
                    ),
                },
            },
            "required": ["prompt"],
            "additionalProperties": False,
        },
        handler=handler,
    )
