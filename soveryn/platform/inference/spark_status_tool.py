"""`spark_status` — let an agent read the machine it runs on.

Vett and Scotty moved onto the Spark on 2026-08-02 (Laguna-S-2.1 on vLLM at
10.10.10.2:8000). Vett could describe the move, reason about it, and research
vLLM flags for it — and could not observe a single fact about the host executing
her. Every number came through Jon.

That is this week's defect wearing yet another costume: the data existed the
whole time at `/api/system/spark`, and no agent had a path to it. Seven such
gaps surfaced in one week, each fixed by adding a read path rather than by
changing a prompt.

Read-only on purpose. This answers "what is true of the Spark right now"; it
does not restart services, evict models or change configuration. An agent that
can see its host is better grounded; an agent that can restart its own inference
server is a different risk conversation, and one to have deliberately.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Mapping

from soveryn.platform.tools.registry import ToolSpec

DEFAULT_URL = "http://127.0.0.1:5001/api/system/spark"
DEFAULT_TIMEOUT = 15


def build_spark_status_tool(
    *, owner_agent: str, url: str = DEFAULT_URL, timeout: int = DEFAULT_TIMEOUT
) -> ToolSpec:
    """Read live Spark state: reachability, vLLM, containers.

    Reads through vNext's own endpoint rather than probing the Spark directly,
    so there is ONE implementation of "what is the Spark doing" shared by
    Mission Control, the mobile app and the agents. A second probe would drift
    from the first and the two would disagree — which is how a fleet ends up
    with two truths and no way to tell which is stale.
    """

    def handler(args: Mapping[str, Any]) -> Any:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                data = json.loads(r.read())
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            # Say the probe failed. Do NOT return an empty/healthy-looking
            # shape — an agent reading "no problems" from a failed read is the
            # exact error this whole line of work documents.
            return {
                "ok": False,
                "error": f"could not read Spark status: {type(exc).__name__}: {exc}",
                "note": "This is a FAILED READ, not an all-clear. Nothing is known "
                        "about the Spark from this result.",
            }

        containers = data.get("containers") or []
        running = [c for c in containers if str(c.get("state", "")).lower() == "running"]
        vllm = data.get("vllm") or {}
        serving = bool(vllm.get("model"))

        # Say the load-bearing thing FIRST and in words. The earlier version led
        # with an empty container list and a set of zeroed counters, and Vett
        # correctly read that as "the machine is idle, I am not on it" — while
        # vLLM was serving her every token. Laguna runs as a systemd unit, NOT a
        # container, so `containers` says nothing about whether inference is up.
        return {
            "ok": True,
            "summary": (
                f"vLLM is serving '{vllm.get('model')}' on the Spark — this is the "
                "backend running Vett and Scotty right now."
                if serving else
                "vLLM reports no model loaded. Inference for Vett and Scotty is "
                "NOT being served from here."
            ),
            "inference_serving": serving,
            "inference_model": vllm.get("model"),
            "you_run_here": serving,
            "reachable": data.get("available"),
            "path": data.get("path"),      # "fabric" = the CX-7 link
            "vllm_detail": vllm,
            # Idle counters are NOT evidence of being down. A model with no
            # in-flight request reports zeros and is perfectly healthy.
            "vllm_counters_note": (
                "requests_running/kv_cache_pct of 0 mean idle, not stopped."
            ),
            "docker_containers_total": len(containers),
            "docker_containers_running": [c.get("name") for c in running],
            "docker_note": (
                "Docker containers are UNRELATED to inference on this host. "
                "Laguna runs as the laguna-serve systemd unit. An empty list "
                "here does not mean inference is down."
            ),
            "message": data.get("message") or "",
            "fetched_at": data.get("fetched_at"),
        }

    return ToolSpec(
        name="spark_status",
        owner=owner_agent,
        description=(
            "Read live status of the DGX Spark (10.10.10.2): whether it is "
            "reachable, what vLLM reports, and which containers are running. "
            "Vett and Scotty run their inference there. Read-only. If the probe "
            "fails it returns ok=false — treat that as 'unknown', never as 'healthy'."
        ),
        schema={"type": "object", "properties": {}, "required": []},
        handler=handler,
    )


def register_spark_status_tool(registry, *, owner_agent: str,
                               url: str = DEFAULT_URL) -> None:
    registry.register(build_spark_status_tool(owner_agent=owner_agent, url=url))
