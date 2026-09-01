"""Kernel — SOVERYN local build brain (GLM-5.3-Flash EXL3 under the hood).

House name: Kernel. Live weights: GLM-5.3-Flash TP=2 on both Sparks.
API ``http://10.10.10.2:8001`` alias ``glm-5.3-flash``. DeepSeek Flash GGUF parked.
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

ROUTER_BASE = "http://10.10.10.2:8001"
MODEL_ALIAS = "glm-5.3-flash"
# Live weights are on the Sparks, not a tower GGUF. Path is display-only.
ENTRY_SHARD = Path("/home/soverynspark/models/GLM-5.3-Flash-EXL3-TR3-4bpw")
WEIGHTS_DIR = ENTRY_SHARD
AIDER_CMD = (
    "AIDER_BASE=http://10.10.10.2:8001/v1 "
    "AIDER_MODEL=openai/glm-5.3-flash soveryn-aider"
)
OPENCODE_CMD = "soveryn-opencode"
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
    soveryn_opencode: str = OPENCODE_CMD
    talk_path: str = "/build"
    note: str = (
        "Kernel — house build brain. "
        "OpenCode / Aider / Messages: GLM-5.3-Flash TP=2 on Sparks :8001 "
        "(`soveryn-opencode`, `soveryn-aider --kernel`). "
        "Quadros :8091 Qwen 3.8 is Eve + public, not Kernel."
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
    models = _http_json(f"{ROUTER_BASE}/v1/models", timeout=3.0)
    st.router_ok = models is not None
    listed = False
    llama_status = None
    for m in (models or {}).get("data") or []:
        mid = m.get("id") or ""
        aliases = m.get("aliases") or []
        if mid == MODEL_ALIAS or MODEL_ALIAS in aliases:
            listed = True
            llama_status = (m.get("status") or {}).get("value")
            break

    # vLLM /v1/models has no llama.cpp status.value — listed means serving.
    st.weights_ok = listed
    st.model_status = llama_status or ("loaded" if listed else None)

    with _lock:
        st.warm_job = dict(_warm_state)

    if not st.router_ok:
        st.state = "router_down"
        return st
    if st.warm_job.get("status") == "loading":
        st.state = "loading"
        return st
    if listed:
        st.state = "warm"
        return st
    st.state = "missing"
    st.note = st.note + " GLM not listed on Spark :8001."
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
    tools: bool = True,
    max_tool_rounds: int = 6,
) -> dict[str, Any]:
    """Chat with Kernel. tools=True enables HITL tool loop (default)."""
    msg = (message or "").strip()
    if not msg:
        return {"ok": False, "error": "empty_message"}
    status = get_status()
    if not status.weights_ok:
        return {"ok": False, "error": "weights_missing"}
    if not status.router_ok:
        return {"ok": False, "error": "router_down"}

    if not tools:
        return _chat_plain(msg, history=history, max_tokens=max_tokens,
                           temperature=temperature, status=status)

    from soveryn.app.services.kernel_hitl import (
        handle_tool_call,
        parse_tool_calls,
        strip_tool_fences,
        tool_system_prompt,
    )

    messages: list[dict[str, str]] = [{"role": "system", "content": tool_system_prompt()}]
    for h in history or []:
        role = h.get("role")
        content = (h.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": msg})

    timeout = CHAT_TIMEOUT_S if status.state == "warm" else WARM_TIMEOUT_S
    transcript: list[dict[str, Any]] = []
    proposals: list[dict[str, Any]] = []
    total_lat = 0.0
    last_usage = None
    final_content = ""

    for _round in range(max(1, min(max_tool_rounds, 8))):
        try:
            data = _post_chat(
                messages,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout,
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "error": str(exc)[:500],
                "transcript": transcript,
                "proposals": proposals,
            }

        total_lat += float(data.get("_client_latency_s") or 0)
        last_usage = data.get("usage")
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

        messages.append({"role": "assistant", "content": content})
        transcript.append({"role": "assistant", "content": content})

        calls = parse_tool_calls(content)
        if not calls:
            final_content = strip_tool_fences(content) or content
            break

        # Execute tools; feed results back
        tool_notes: list[str] = []
        for call in calls:
            result = handle_tool_call(call)
            transcript.append({"role": "tool", "content": result})
            if result.get("proposal_id"):
                proposals.append(
                    {
                        "id": result["proposal_id"],
                        "tool": result.get("tool"),
                        "summary": result.get("summary"),
                        "status": result.get("status") or "pending",
                    }
                )
            if result.get("ok"):
                tool_notes.append(
                    f"Tool {result.get('tool')} → {result.get('result', '')[:6000]}"
                )
            else:
                tool_notes.append(
                    f"Tool {result.get('tool')} ERROR → {result.get('error')}"
                )

        # If only approval tools (no auto results to continue on), stop after proposing
        only_pending = all(
            (not c.get("auto")) and c.get("proposal_id")
            for c in (transcript[i]["content"] for i in range(len(transcript))
                      if transcript[i].get("role") == "tool"
                      and isinstance(transcript[i].get("content"), dict))
            if isinstance(c, dict)
        )
        # Simpler: if any auto tool ran, continue; if only proposals, one more model turn to summarize
        any_auto = any(
            isinstance(t.get("content"), dict) and t["content"].get("auto")
            for t in transcript
            if t.get("role") == "tool"
        )
        messages.append(
            {
                "role": "user",
                "content": (
                    "Tool results:\n" + "\n\n".join(tool_notes) + "\n\n"
                    "Continue. If proposals are pending, list their ids and wait — "
                    "do not invent outcomes. If you have enough, summarize for the operator."
                ),
            }
        )
        if not any_auto and proposals:
            # one more model turn for summary then stop after next loop iteration sets final
            try:
                data2 = _post_chat(
                    messages,
                    max_tokens=min(max_tokens, 600),
                    temperature=temperature,
                    timeout=timeout,
                )
                total_lat += float(data2.get("_client_latency_s") or 0)
                last_usage = data2.get("usage") or last_usage
                c2 = ((data2.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
                final_content = strip_tool_fences(c2) or c2
                transcript.append({"role": "assistant", "content": c2})
            except Exception:
                final_content = strip_tool_fences(content) or content
            break
    else:
        final_content = strip_tool_fences(
            next(
                (t["content"] for t in reversed(transcript) if t.get("role") == "assistant"),
                "",
            )
        )

    return {
        "ok": True,
        "content": final_content,
        "transcript": transcript,
        "proposals": proposals,
        "tools_enabled": True,
        "usage": last_usage,
        "latency_s": round(total_lat, 3),
        "model": MODEL_ALIAS,
    }


def _chat_plain(
    msg: str,
    *,
    history: list[dict[str, str]] | None,
    max_tokens: int,
    temperature: float,
    status: BenchFlashStatus,
) -> dict[str, Any]:
    try:
        from soveryn.agents.personas import get_persona
        system = get_persona("kernel")
    except Exception:
        system = (
            "You are Kernel, the SOVERYN house build brain. "
            "You run locally (GLM-5.3-Flash EXL3 on dual Spark). "
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
        "tools_enabled": False,
        "usage": data.get("usage"),
        "latency_s": data.get("_client_latency_s"),
        "model": MODEL_ALIAS,
        "finish_reason": choice.get("finish_reason"),
    }
