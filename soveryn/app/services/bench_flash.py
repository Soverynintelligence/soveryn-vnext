"""Kernel — SOVERYN local build brain (DeepSeek V4 Flash under the hood).

House name: Kernel (chosen in-house). Model: DeepSeek-V4-Flash-0731.
Weights on NVMe; quadro router alias ``bench-flash`` on :8091.
Command Center uses this so operators can warm and talk without CLI.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROUTER_BASE = "http://127.0.0.1:8091"
MODEL_ALIAS = "bench-flash"
ENTRY_SHARD = Path(
    "/mnt/soveryn_models/GGUF/DeepSeek-V4-Flash-0731/UD-Q4_K_XL/"
    "DeepSeek-V4-Flash-0731-UD-Q4_K_XL-00001-of-00005.gguf"
)
WEIGHTS_DIR = ENTRY_SHARD.parent
AIDER_CMD = (
    "AIDER_BASE=http://127.0.0.1:8091/v1 "
    "AIDER_MODEL=openai/bench-flash soveryn-aider"
)
HOUSE_NAME = "Kernel"
# First load of ~145G multi-shard GGUF can take a long time.
WARM_TIMEOUT_S = 900
CHAT_TIMEOUT_S = 300

_lock = threading.Lock()
_warm_state: dict[str, Any] = {
    "status": "idle",  # idle | loading | ok | error
    "started_at": None,
    "finished_at": None,
    "error": None,
    "latency_s": None,
}


@dataclass
class BenchFlashStatus:
    name: str = HOUSE_NAME
    alias: str = MODEL_ALIAS
    router: str = ROUTER_BASE
    weights_ok: bool = False
    weights_path: str = str(ENTRY_SHARD)
    weights_dir: str = str(WEIGHTS_DIR)
    router_ok: bool = False
    # cold | warm | loading | missing | router_down
    state: str = "missing"
    model_status: str | None = None  # loaded | unloaded | None
    warm_job: dict[str, Any] = field(default_factory=dict)
    aider_cmd: str = AIDER_CMD
    soveryn_aider_flash: str = "soveryn-aider --kernel"
    talk_path: str = "/build"
    note: str = (
        "Kernel — house build brain (DeepSeek V4 Flash). "
        "145G multi-shard GGUF, Quadros + system RAM spill. "
        "First warm can take several minutes."
    )
    fetched_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _http_json(url: str, *, timeout: float = 5.0) -> Any | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def _post_chat(
    messages: list[dict[str, str]],
    *,
    max_tokens: int = 256,
    temperature: float = 0.2,
    timeout: float = CHAT_TIMEOUT_S,
) -> dict[str, Any]:
    body = json.dumps(
        {
            "model": MODEL_ALIAS,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{ROUTER_BASE}/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")[:800]
        except Exception:  # noqa: BLE001
            body = ""
        detail = body or str(exc)
        raise RuntimeError(f"router HTTP {exc.code}: {detail}") from exc
    data["_client_latency_s"] = round(time.perf_counter() - t0, 3)
    return data


def get_status() -> BenchFlashStatus:
    st = BenchFlashStatus(
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )
    st.weights_ok = ENTRY_SHARD.is_file()
    models = _http_json(f"{ROUTER_BASE}/v1/models", timeout=3.0)
    st.router_ok = models is not None

    with _lock:
        st.warm_job = dict(_warm_state)

    if not st.weights_ok:
        st.state = "missing"
        return st
    if not st.router_ok:
        st.state = "router_down"
        return st

    model_status = None
    for m in (models or {}).get("data") or []:
        mid = m.get("id") or ""
        aliases = m.get("aliases") or []
        if mid == MODEL_ALIAS or MODEL_ALIAS in aliases or mid in (
            "deepseek-flash",
            "deepseek-v4-flash",
            "DeepSeek-V4-Flash-0731",
        ):
            ms = (m.get("status") or {}).get("value")
            model_status = ms
            break
        # Also match if id is bench-flash
        if "flash" in mid.lower() and "deepseek" in mid.lower():
            model_status = (m.get("status") or {}).get("value")
            break

    # Prefer exact alias scan
    for m in (models or {}).get("data") or []:
        if m.get("id") == MODEL_ALIAS:
            model_status = (m.get("status") or {}).get("value")
            break

    st.model_status = model_status

    if st.warm_job.get("status") == "loading":
        st.state = "loading"
    elif model_status == "loaded":
        st.state = "warm"
    elif model_status in (None, "unloaded"):
        # preset may be listed as unloaded, or only appear once first requested
        if model_status is None:
            # preset missing from router — still cold if weights exist
            st.state = "cold"
            st.note = (
                st.note
                + " Preset not listed on router — restart soveryn-router-quadro if needed."
            )
        else:
            st.state = "cold"
    else:
        st.state = "cold"

    return st


def _run_warm() -> None:
    global _warm_state
    t0 = time.perf_counter()
    try:
        _post_chat(
            [{"role": "user", "content": "Reply with exactly: ready"}],
            max_tokens=8,
            temperature=0,
            timeout=WARM_TIMEOUT_S,
        )
        with _lock:
            _warm_state.update(
                {
                    "status": "ok",
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "error": None,
                    "latency_s": round(time.perf_counter() - t0, 3),
                }
            )
    except Exception as exc:  # noqa: BLE001 — surface any load failure to UI
        with _lock:
            _warm_state.update(
                {
                    "status": "error",
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "error": str(exc)[:500],
                    "latency_s": round(time.perf_counter() - t0, 3),
                }
            )


def start_warm() -> dict[str, Any]:
    """Kick a background warm if not already loading/warm."""
    status = get_status()
    if not status.weights_ok:
        return {"ok": False, "error": "weights_missing", "status": status.as_dict()}
    if not status.router_ok:
        return {"ok": False, "error": "router_down", "status": status.as_dict()}
    if status.state == "warm":
        return {"ok": True, "already": "warm", "status": status.as_dict()}

    with _lock:
        if _warm_state.get("status") == "loading":
            return {
                "ok": True,
                "already": "loading",
                "status": get_status().as_dict(),
            }
        _warm_state.update(
            {
                "status": "loading",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "finished_at": None,
                "error": None,
                "latency_s": None,
            }
        )

    t = threading.Thread(target=_run_warm, name="kernel-warm", daemon=True)
    t.start()
    return {"ok": True, "started": True, "status": get_status().as_dict()}


def chat(
    message: str,
    *,
    history: list[dict[str, str]] | None = None,
    max_tokens: int = 1024,
    temperature: float = 0.2,
) -> dict[str, Any]:
    """One-shot chat proxy to Kernel (no agent loop / tools)."""
    msg = (message or "").strip()
    if not msg:
        return {"ok": False, "error": "empty_message"}
    status = get_status()
    if not status.weights_ok:
        return {"ok": False, "error": "weights_missing"}
    if not status.router_ok:
        return {"ok": False, "error": "router_down"}

    system = (
        "You are Kernel, the SOVERYN house build brain. "
        "You run locally (DeepSeek V4 Flash weights). "
        "You make and mend code — patches, refactors, technical work. "
        "You are not the soul, not the verifier, not the political executor. "
        "Be direct. Prefer concrete patches and commands over essays."
    )
    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    for h in history or []:
        role = h.get("role")
        content = (h.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": msg})

    try:
        data = _post_chat(
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=CHAT_TIMEOUT_S if status.state == "warm" else WARM_TIMEOUT_S,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:500]}

    choice = (data.get("choices") or [{}])[0]
    message_out = choice.get("message") or {}
    content = (message_out.get("content") or "").strip()
    reasoning = (
        message_out.get("reasoning_content")
        or message_out.get("reasoning")
        or ""
    )
    if not content and reasoning:
        content = str(reasoning).strip()
    return {
        "ok": True,
        "content": content,
        "usage": data.get("usage"),
        "latency_s": data.get("_client_latency_s"),
        "model": MODEL_ALIAS,
        "finish_reason": choice.get("finish_reason"),
    }
