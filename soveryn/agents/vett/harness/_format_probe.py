"""Phase 1 blocker probe: send a harness-shape message to Vett.

This isolates the format-compat question from the full inference
model implementation. If it fails, we know it before writing more
SOVERYN-side glue code.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

import httpx


@dataclass
class FormatProbeResult:
    ok: bool
    response_text: str
    reason: Optional[str] = None


# A reduced harness-shape message: system prompt with tool-instructions
# echo + a user query. This mirrors the simplest case the harness can
# emit. If Vett can't handle this, she can't handle the real thing.
_HARNESS_SHAPE_SYSTEM = (
    "You are a research subagent. You have access to tools to search a "
    "corpus, read documents, and verify claims. Plan your research before "
    "acting. Reply briefly to confirm you understand the task."
)
_HARNESS_SHAPE_USER = (
    "Confirm by replying with exactly the phrase: HARNESS_OK"
)


def probe_vett_format_compat(*, router_url: str, model: str) -> FormatProbeResult:
    """Send a harness-shape message; assert response is non-empty + non-error.

    NOTE on max_tokens: Vett (Qwen3.6-27B) is served with
    ``--reasoning on`` + ``--reasoning-format deepseek``. The router routes
    chain-of-thought into ``message.reasoning_content`` and visible content
    into ``message.content``. A small budget (e.g. 32) is consumed entirely
    by hidden thinking and yields empty ``content`` with
    ``finish_reason="length"`` — which would look like a format failure but
    isn't. We use 256 so visible content has room to emit; the harness's
    real inference path will use realistic per-turn budgets too.
    """
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _HARNESS_SHAPE_SYSTEM},
            {"role": "user", "content": _HARNESS_SHAPE_USER},
        ],
        "max_tokens": 256,
        "temperature": 0.0,
    }
    try:
        resp = httpx.post(f"{router_url}/v1/chat/completions", json=payload, timeout=30.0)
    except httpx.HTTPError as e:
        return FormatProbeResult(ok=False, response_text="", reason=f"HTTP error: {e}")
    if resp.status_code != 200:
        return FormatProbeResult(ok=False, response_text="", reason=f"status={resp.status_code} body={resp.text[:200]}")
    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, ValueError) as e:
        return FormatProbeResult(ok=False, response_text="", reason=f"unexpected response shape: {e}, body={resp.text[:200]}")
    return FormatProbeResult(ok=True, response_text=content.strip())
