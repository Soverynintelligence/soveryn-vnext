"""Kokoro-82M TTS provider — in-process, local snapshot only.

Does **not** use Pipecat ``KokoroTTSService`` (that path downloads ONNX).
Loads hexgrad Kokoro-82M from a pinned Hugging Face snapshot on disk and
yields WAV chunks in the same shape as :class:`F5TTSProvider`.

HF_HUB_OFFLINE is required. Voices and weights are resolved as absolute
local paths; we never call ``hf_hub_download``.

GPU: helper Quadro ``GPU-305d1801-…`` only. Blackwell and the other
Quadro are refused.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import subprocess
import threading
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from soveryn.platform.voice.providers.base import TTSChunk, TTSError, TTSProvider


logger = logging.getLogger(__name__)

DEFAULT_SAMPLE_RATE = 24000  # Kokoro v1.0 native
DEFAULT_VOICE = "af_heart"
DEFAULT_SNAPSHOT = Path(
    "/home/jon-deoliveira/.cache/huggingface/hub/"
    "models--hexgrad--Kokoro-82M/snapshots/"
    "f3ff3571791e39611d31c381e3a41a3af07b4987"
)
HELPER_GPU_UUID = "GPU-305d1801-319e-3330-d75e-0676387a91f2"
BLACKWELL_GPU_UUID = "GPU-946b08b0-e9d3-949b-6eab-b6c5b8a5f5cd"

# Agent names from the voice registry → Kokoro voice stem.
AGENT_TO_VOICE = {
    "aetheria": "af_heart",
    "eve": "af_heart",
    "kernel": "af_heart",
    # Folded names still resolve if something old asks.
    "vett": "af_heart",
    "scotty": "af_heart",
}

_ENGINE: "_KokoroEngine | None" = None
_ENGINE_LOCK = threading.Lock()


def _snapshot_dir() -> Path:
    raw = os.environ.get("SOVERYN_KOKORO_SNAPSHOT", "").strip()
    return Path(raw) if raw else DEFAULT_SNAPSHOT


def _config_path() -> Path:
    raw = os.environ.get("SOVERYN_KOKORO_CONFIG", "").strip()
    return Path(raw) if raw else _snapshot_dir() / "config.json"


def _model_path() -> Path:
    raw = os.environ.get("SOVERYN_KOKORO_MODEL", "").strip()
    return Path(raw) if raw else _snapshot_dir() / "kokoro-v1_0.pth"


def _voices_dir() -> Path:
    raw = os.environ.get("SOVERYN_KOKORO_VOICES_DIR", "").strip()
    return Path(raw) if raw else _snapshot_dir() / "voices"


def resolve_kokoro_voice(agent_or_voice: str | None) -> str:
    """Map an agent name / env override to a Kokoro voice stem."""
    env = (os.environ.get("SOVERYN_KOKORO_VOICE") or "").strip()
    if env:
        return env[:-3] if env.endswith(".pt") else env
    name = (agent_or_voice or DEFAULT_VOICE).strip()
    if not name:
        return DEFAULT_VOICE
    key = name.lower()
    if key in AGENT_TO_VOICE:
        return AGENT_TO_VOICE[key]
    if key.endswith(".pt"):
        return Path(name).stem
    return name


def _voice_pt(voice_id: str) -> Path:
    name = resolve_kokoro_voice(voice_id)
    voices = _voices_dir()
    if name.endswith(".pt"):
        path = Path(name)
    elif "/" in name or name.startswith("."):
        path = Path(name)
    else:
        path = voices / f"{name}.pt"
    if not path.is_file():
        raise TTSError(f"Kokoro voice not found locally: {path}")
    return path


def _lang_code_for_voice(stem: str) -> str:
    # Kokoro convention: a* American, b* British, i* Italian, …
    if stem.startswith("b"):
        return "b"
    return "a"


def _smi_uuid_index() -> dict[str, int]:
    out = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=index,uuid", "--format=csv,noheader"],
        text=True,
    )
    mapping: dict[str, int] = {}
    for line in out.strip().splitlines():
        if not line.strip():
            continue
        idx, uuid = [part.strip() for part in line.split(",", 1)]
        mapping[uuid] = int(idx)
    return mapping


def _torch_index_for_uuid(uuid: str) -> int:
    """Map a GPU UUID onto the current process's torch device index."""
    if uuid == BLACKWELL_GPU_UUID:
        raise TTSError("refusing to load Kokoro on Blackwell (Aetheria llama)")
    smi = _smi_uuid_index()
    if uuid not in smi:
        raise TTSError(f"Kokoro helper GPU {uuid} not present in nvidia-smi")
    smi_idx = smi[uuid]
    visible = os.environ.get("CUDA_VISIBLE_DEVICES", "").strip()
    if not visible:
        return smi_idx
    parts = [p.strip() for p in visible.split(",") if p.strip()]
    for torch_i, part in enumerate(parts):
        if part == uuid or part == str(smi_idx):
            return torch_i
    raise TTSError(
        f"Kokoro helper GPU {uuid} is not in CUDA_VISIBLE_DEVICES={visible!r}"
    )


def _allow_transformers_hub_v1() -> None:
    """transformers 4.57.x pins huggingface-hub<1.0; soveryn has hub 1.4.1.

    Kokoro only needs AlbertConfig / AlbertModel classes from the already
    installed transformers. Patch importlib.metadata for the duration of
    the import, then restore.
    """
    import importlib.metadata as im

    orig = im.version

    def _version(pkg: str, *a: Any, **k: Any) -> str:
        if pkg in ("huggingface-hub", "huggingface_hub"):
            return "0.36.0"
        return orig(pkg, *a, **k)

    im.version = _version  # type: ignore[method-assign]
    try:
        import transformers  # noqa: F401
        from kokoro import KModel, KPipeline  # noqa: F401
    finally:
        im.version = orig  # type: ignore[method-assign]


def _import_kokoro():
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("CUDA_DEVICE_ORDER", "PCI_BUS_ID")
    try:
        from kokoro import KModel, KPipeline
        return KModel, KPipeline
    except ImportError as exc:
        msg = str(exc)
        if "huggingface-hub" not in msg and "huggingface_hub" not in msg:
            raise
        _allow_transformers_hub_v1()
        from kokoro import KModel, KPipeline
        return KModel, KPipeline


def _float_to_wav(audio, sample_rate: int) -> bytes:
    import numpy as np
    import soundfile as sf

    arr = np.asarray(audio, dtype=np.float32)
    if arr.ndim > 1:
        arr = arr.reshape(-1)
    peak = float(np.max(np.abs(arr))) if arr.size else 0.0
    if peak > 1.0:
        arr = arr / peak
    buf = io.BytesIO()
    sf.write(buf, arr, sample_rate, format="WAV", subtype="PCM_16")
    return buf.getvalue()


class _KokoroEngine:
    """Process-wide KModel + per-lang KPipeline. Local paths only."""

    def __init__(self) -> None:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        os.environ.setdefault("CUDA_DEVICE_ORDER", "PCI_BUS_ID")

        cfg = _config_path()
        pth = _model_path()
        voices = _voices_dir()
        if not cfg.is_file():
            raise TTSError(f"Kokoro config.json missing: {cfg}")
        if not pth.is_file():
            raise TTSError(f"Kokoro weights missing: {pth}")
        if not voices.is_dir():
            raise TTSError(f"Kokoro voices/ missing: {voices}")

        uuid = (
            os.environ.get("SOVERYN_TTS_GPU_UUID", "").strip() or HELPER_GPU_UUID
        )
        torch_index = _torch_index_for_uuid(uuid)

        KModel, KPipeline = _import_kokoro()
        import torch

        if not torch.cuda.is_available():
            raise TTSError("Kokoro requires CUDA on the helper Quadro")
        if torch_index >= torch.cuda.device_count():
            raise TTSError(
                f"Kokoro torch index {torch_index} out of range "
                f"(count={torch.cuda.device_count()})"
            )
        device = torch.device(f"cuda:{torch_index}")
        name = torch.cuda.get_device_name(torch_index)
        if "Blackwell" in name or "PRO 5000" in name:
            raise TTSError(f"refusing Kokoro on {name}")

        logger.info(
            "Kokoro loading snapshot=%s model=%s device=%s uuid=%s name=%s",
            _snapshot_dir(),
            pth,
            device,
            uuid,
            name,
        )
        # repo_id is unused when config+model are local paths; still pass the
        # canonical id so KModel.MODEL_NAMES lookups would not KeyError if a
        # future caller omitted `model`.
        self.model = (
            KModel(
                repo_id="hexgrad/Kokoro-82M",
                config=str(cfg),
                model=str(pth),
            )
            .to(device)
            .eval()
        )
        self.device = device
        self.KPipeline = KPipeline
        self._pipes: dict[str, Any] = {}
        self._infer_lock = threading.Lock()
        logger.info("Kokoro ready on %s (%s)", device, name)

    def pipe_for(self, lang_code: str):
        pipe = self._pipes.get(lang_code)
        if pipe is not None:
            return pipe
        # Quiet HF hub: we never load voices through repo_id.
        pipe = self.KPipeline(
            lang_code=lang_code,
            repo_id="hexgrad/Kokoro-82M",
            model=self.model,
            device=str(self.device),
        )
        self._pipes[lang_code] = pipe
        return pipe

    def synthesize_sync(self, text: str, voice_pt: Path) -> list[bytes]:
        stem = voice_pt.stem
        lang = _lang_code_for_voice(stem)
        pipe = self.pipe_for(lang)
        wavs: list[bytes] = []
        with self._infer_lock:
            for result in pipe(text, voice=str(voice_pt), speed=1.0):
                audio = result.audio
                if audio is None:
                    continue
                wavs.append(
                    _float_to_wav(audio.detach().cpu().numpy(), DEFAULT_SAMPLE_RATE)
                )
        return wavs


def get_engine() -> _KokoroEngine:
    global _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is None:
            _ENGINE = _KokoroEngine()
        return _ENGINE


class KokoroTTSProvider(TTSProvider):
    """In-process Kokoro TTS. Constructor does not touch the GPU."""

    def __init__(self, *, sample_rate: int = DEFAULT_SAMPLE_RATE) -> None:
        self.sample_rate = sample_rate
        self._cancel_observed = False
        self.clauses_completed_after_cancel: int = 0

    @property
    def name(self) -> str:
        return "kokoro"

    async def abort(self) -> None:
        self._cancel_observed = True

    async def synthesize(
        self,
        text: str,
        *,
        voice_id: str,
        cancel_event: asyncio.Event | None = None,
    ) -> AsyncIterator[TTSChunk]:
        if not text.strip():
            return
        self.clauses_completed_after_cancel = 0
        self._cancel_observed = False
        try:
            voice_pt = _voice_pt(voice_id)
        except TTSError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise TTSError(f"Kokoro voice resolve failed: {exc}") from exc

        if cancel_event is not None and cancel_event.is_set():
            self._cancel_observed = True
            yield TTSChunk(audio_bytes=b"", sample_rate=self.sample_rate, is_final=True)
            return

        try:
            engine = await asyncio.to_thread(get_engine)
            wavs = await asyncio.to_thread(engine.synthesize_sync, text, voice_pt)
        except TTSError:
            raise
        except Exception as exc:  # noqa: BLE001
            if self._cancel_observed or (
                cancel_event is not None and cancel_event.is_set()
            ):
                logger.debug("Kokoro synth ended after cancel: %s", exc)
                yield TTSChunk(
                    audio_bytes=b"", sample_rate=self.sample_rate, is_final=True
                )
                return
            raise TTSError(
                f"Kokoro synthesis failed: {type(exc).__name__}: {exc}"
            ) from exc

        for wav in wavs:
            if self._cancel_observed or (
                cancel_event is not None and cancel_event.is_set()
            ):
                self._cancel_observed = True
                self.clauses_completed_after_cancel += 1
                break
            if not wav:
                continue
            yield TTSChunk(
                audio_bytes=wav, sample_rate=self.sample_rate, is_final=False
            )
        yield TTSChunk(audio_bytes=b"", sample_rate=self.sample_rate, is_final=True)


__all__ = [
    "AGENT_TO_VOICE",
    "DEFAULT_SAMPLE_RATE",
    "DEFAULT_SNAPSHOT",
    "DEFAULT_VOICE",
    "HELPER_GPU_UUID",
    "KokoroTTSProvider",
    "get_engine",
    "resolve_kokoro_voice",
]
