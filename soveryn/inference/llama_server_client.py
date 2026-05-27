"""SOVERYN vNext — non-streaming llama-server client.

Sync wrapper over urllib.request for llama-server's OpenAI-compatible
endpoints:
  - POST /v1/chat/completions  (chat)
  - POST /v1/embeddings        (embed — embeddings server only)

NOT in scope here:
  - streaming / SSE
  - tool-call dispatch (raw passthrough only)
  - persona assembly / prompt templating
  - conversation history management
  - retries
  - async

The caller already knows which ModelServer to talk to (via routing).
This module's job is request marshalling, error typing, and response
parsing — nothing more.
"""

from __future__ import annotations
import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Iterator

from soveryn.config.runtime import MODEL_SERVERS, ModelServer


DEFAULT_CHAT_TIMEOUT_SECONDS = 30.0
DEFAULT_EMBED_TIMEOUT_SECONDS = 10.0
EMBEDDINGS_SERVER_NAME = "embeddings"


# ─────────────────────────────────────────────────────────────────────────────
# Typed errors
# ─────────────────────────────────────────────────────────────────────────────

class LlamaServerError(Exception):
    """Non-2xx response or transport failure from a llama-server."""

    def __init__(self, status_code: int, detail: str, server_name: str) -> None:
        super().__init__(f"{server_name}: HTTP {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail
        self.server_name = server_name


class LlamaServerTimeout(Exception):
    """Request to a llama-server exceeded its timeout."""

    def __init__(self, server_name: str, timeout_seconds: float) -> None:
        super().__init__(f"{server_name}: timeout after {timeout_seconds}s")
        self.server_name = server_name
        self.timeout_seconds = timeout_seconds


# ─────────────────────────────────────────────────────────────────────────────
# Request / response shapes (frozen, stdlib only)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ChatMessage:
    role: str          # "system" | "user" | "assistant" | "tool"
    content: str
    # NOTE: requests don't model assistant tool_calls here — vNext doesn't
    # send assistant turns back with tool_calls yet. If/when it does, add.


@dataclass(frozen=True)
class ChatRequest:
    messages: tuple[ChatMessage, ...]
    model: str                            # logical model name; llama-server ignores beyond labelling
    temperature: float = 0.7
    max_tokens: int = 2048
    top_p: float | None = None
    stop: tuple[str, ...] | None = None
    tools: tuple[dict, ...] | None = None   # OpenAI-schema passthrough


@dataclass(frozen=True)
class ChatResponse:
    content: str                            # assistant message text
    finish_reason: str                      # "stop" | "length" | "tool_calls" | etc.
    tool_calls: tuple[dict, ...] | None     # raw, uninterpreted
    usage: dict[str, int] | None            # prompt_tokens / completion_tokens / total_tokens
    raw: dict                               # full response for debugging


@dataclass(frozen=True)
class EmbeddingRequest:
    input: tuple[str, ...]                  # always a sequence; single-string callers wrap to (s,)
    model: str = "nomic-embed-text-v1.5"


@dataclass(frozen=True)
class EmbeddingResponse:
    vectors: tuple[tuple[float, ...], ...]  # parallel to request.input
    usage: dict[str, int] | None
    raw: dict


# ─────────────────────────────────────────────────────────────────────────────
# Internal HTTP helper
# ─────────────────────────────────────────────────────────────────────────────

def _post_json(
    url: str,
    payload: dict,
    timeout: float,
    server_name: str,
) -> dict:
    """POST JSON, parse JSON. Convert any failure into the typed errors above."""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as e:
                raise LlamaServerError(
                    status_code=resp.status,
                    detail=f"non-JSON response: {e}",
                    server_name=server_name,
                )
            if not (200 <= resp.status < 300):
                raise LlamaServerError(
                    status_code=resp.status,
                    detail=str(parsed)[:500],
                    server_name=server_name,
                )
            return parsed
    except urllib.error.HTTPError as e:
        # urllib raises HTTPError for non-2xx; capture body if present
        body_text = ""
        try:
            body_text = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        raise LlamaServerError(
            status_code=e.code,
            detail=body_text or e.reason,
            server_name=server_name,
        )
    except (socket.timeout, TimeoutError):
        raise LlamaServerTimeout(server_name=server_name, timeout_seconds=timeout)
    except urllib.error.URLError as e:
        raise LlamaServerError(
            status_code=0,
            detail=f"URLError: {e.reason}",
            server_name=server_name,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def chat(
    request: ChatRequest,
    server: ModelServer,
    timeout: float = DEFAULT_CHAT_TIMEOUT_SECONDS,
) -> ChatResponse:
    """Send a non-streaming chat completion. Caller picks the server (via routing)."""
    payload: dict[str, Any] = {
        "model": request.model,
        "messages": [{"role": m.role, "content": m.content} for m in request.messages],
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
        "stream": False,
    }
    if request.top_p is not None:
        payload["top_p"] = request.top_p
    if request.stop is not None:
        payload["stop"] = list(request.stop)
    if request.tools is not None:
        payload["tools"] = [dict(t) for t in request.tools]

    url = f"http://127.0.0.1:{server.port}/v1/chat/completions"
    parsed = _post_json(url, payload, timeout, server.name)

    # llama-server emits OpenAI-compat: choices[0].message.{content,tool_calls}, finish_reason
    try:
        choice = parsed["choices"][0]
        message = choice["message"]
        content = message.get("content") or ""
        raw_tool_calls = message.get("tool_calls")
        tool_calls = tuple(raw_tool_calls) if raw_tool_calls else None
        finish_reason = choice.get("finish_reason", "")
    except (KeyError, IndexError, TypeError) as e:
        raise LlamaServerError(
            status_code=200,
            detail=f"unexpected response shape: {e}",
            server_name=server.name,
        )

    return ChatResponse(
        content=content,
        finish_reason=finish_reason,
        tool_calls=tool_calls,
        usage=parsed.get("usage"),
        raw=parsed,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Streaming chat
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_STREAM_TIMEOUT_SECONDS = 120.0  # streams can be long; per-read socket timeout below
DEFAULT_STREAM_READ_TIMEOUT_SECONDS = 60.0  # max gap between chunks
SSE_DATA_PREFIX = "data: "
SSE_DONE_MARKER = "[DONE]"


@dataclass(frozen=True)
class StreamChunk:
    """One parsed chunk from llama-server's SSE stream.

    `delta` is the content delta (may be empty string).
    `finish_reason` is None mid-stream, set on the terminal chunk.
    `tool_calls_delta` is the raw OpenAI tool_calls delta list for this chunk
    (or None). Callers accumulate by index across chunks.
    `raw` is the full parsed chunk dict (preserve for debugging).
    """
    delta: str
    finish_reason: str | None
    tool_calls_delta: list | None
    usage: dict | None
    raw: dict


def chat_stream(
    request: ChatRequest,
    server: ModelServer,
    timeout: float = DEFAULT_STREAM_TIMEOUT_SECONDS,
) -> "Iterator[StreamChunk]":
    """Open a streaming chat completion. Yields StreamChunk per upstream chunk.

    The final chunk has `finish_reason != None`. After that, the upstream may
    emit a literal `data: [DONE]` terminator which we consume but do NOT yield.

    Raises LlamaServerError / LlamaServerTimeout on network failure OR if a
    chunk that looks terminal (contains finish_reason or [DONE]) is malformed.
    """
    payload: dict[str, Any] = {
        "model": request.model,
        "messages": [{"role": m.role, "content": m.content} for m in request.messages],
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
        "stream": True,
    }
    if request.top_p is not None:
        payload["top_p"] = request.top_p
    if request.stop is not None:
        payload["stop"] = list(request.stop)
    if request.tools is not None:
        payload["tools"] = [dict(t) for t in request.tools]

    url = f"http://127.0.0.1:{server.port}/v1/chat/completions"
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        body_text = ""
        try:
            body_text = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        raise LlamaServerError(status_code=e.code, detail=body_text or e.reason,
                               server_name=server.name)
    except (socket.timeout, TimeoutError):
        raise LlamaServerTimeout(server_name=server.name, timeout_seconds=timeout)
    except urllib.error.URLError as e:
        raise LlamaServerError(status_code=0, detail=f"URLError: {e.reason}",
                               server_name=server.name)

    try:
        yield from _parse_sse_chunks(resp, server.name)
    finally:
        try:
            resp.close()
        except Exception:
            pass


def _parse_sse_chunks(resp, server_name: str) -> "Iterator[StreamChunk]":
    """Iterate over `data:` lines from an SSE response. Yields StreamChunk.

    Behavior:
      - Lines not starting with `data: ` are skipped (SSE comments, blank lines, etc.).
      - `data: [DONE]` is recognized as the clean terminator — consumed, not yielded.
      - Lines whose JSON parse fails are skipped IF clearly non-terminal junk,
        but raise LlamaServerError if the line contains `finish_reason` or `[DONE]`
        (looks terminal, must not silently lose).
    """
    for raw_line in resp:
        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
        if not line:
            continue  # blank line between events
        if not line.startswith(SSE_DATA_PREFIX):
            continue  # SSE comment / other event types — ignore
        data = line[len(SSE_DATA_PREFIX):].strip()
        if data == SSE_DONE_MARKER:
            return  # clean terminator
        # Try to parse JSON
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError as e:
            # If this looks terminal-shaped, fail loud per Jon's constraint 7.
            # Check for both `finish_reason` and `[DONE` (catches `[DONE]` and
            # truncated variants like `[DONE` that passed the exact-marker check).
            if "finish_reason" in data or "[DONE" in data:
                raise LlamaServerError(
                    status_code=200,
                    detail=f"malformed terminal SSE chunk: {data[:200]!r} ({e})",
                    server_name=server_name,
                )
            continue  # non-terminal junk — skip

        choices = parsed.get("choices") if isinstance(parsed, dict) else None
        if not choices or not isinstance(choices, list):
            continue
        choice = choices[0]
        if not isinstance(choice, dict):
            continue
        delta_obj = choice.get("delta") or {}
        content_delta = delta_obj.get("content") or ""
        if not isinstance(content_delta, str):
            content_delta = ""
        finish_reason = choice.get("finish_reason")
        tc_delta = delta_obj.get("tool_calls")
        if tc_delta is not None and not isinstance(tc_delta, list):
            tc_delta = None
        usage = parsed.get("usage")
        if usage is not None and not isinstance(usage, dict):
            usage = None
        yield StreamChunk(
            delta=content_delta,
            finish_reason=finish_reason,
            tool_calls_delta=tc_delta,
            usage=usage,
            raw=parsed,
        )


def _embeddings_server() -> ModelServer:
    """Find the single embeddings server. Raises if missing (config bug)."""
    for s in MODEL_SERVERS:
        if s.name == EMBEDDINGS_SERVER_NAME:
            return s
    raise LookupError(
        f"No MODEL_SERVERS entry named {EMBEDDINGS_SERVER_NAME!r} — "
        "embeddings cannot be served"
    )


def embed(
    request: EmbeddingRequest,
    timeout: float = DEFAULT_EMBED_TIMEOUT_SECONDS,
) -> EmbeddingResponse:
    """POST /v1/embeddings to the embeddings server. NO server parameter — embeddings
    are NEVER routed through an agent server (boundary 5).

    Phase 7 (2026-05-26) — under router mode, the "model" field must match a
    preset alias. The embeddings server's `model_alias` is authoritative; the
    EmbeddingRequest.model default ("nomic-embed-text-v1.5") doesn't match any
    router alias, so the server's alias is preferred when set.
    """
    server = _embeddings_server()
    payload = {
        "model": server.model_alias or request.model,
        "input": list(request.input),
    }
    url = f"http://127.0.0.1:{server.port}/v1/embeddings"
    parsed = _post_json(url, payload, timeout, server.name)

    try:
        data = parsed["data"]
        vectors = tuple(tuple(item["embedding"]) for item in data)
    except (KeyError, TypeError) as e:
        raise LlamaServerError(
            status_code=200,
            detail=f"unexpected embeddings shape: {e}",
            server_name=server.name,
        )

    return EmbeddingResponse(
        vectors=vectors,
        usage=parsed.get("usage"),
        raw=parsed,
    )
