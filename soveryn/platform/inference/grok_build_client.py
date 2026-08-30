"""Grok Build CLI backend for the Messages ``grok`` contact.

Invokes headless ``grok -p`` (same auth as the house TUI) so Jon can talk to
the coding agent from Messages without Telegram. AgentLoop tools stay off —
coding tools live inside the grok process.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Iterator

from soveryn.config.runtime import ModelServer
from soveryn.platform.inference.llama_server_client import (
    ChatRequest,
    ChatResponse,
    LlamaServerError,
    LlamaServerTimeout,
    StreamChunk,
)

logger = logging.getLogger(__name__)

DEFAULT_GROK_BIN = Path.home() / ".grok" / "bin" / "grok"
DEFAULT_CWD = Path("/home/jon-deoliveira/soveryn_vnext")
DEFAULT_TIMEOUT = 900.0
DEFAULT_MAX_TURNS = 40

# Paths grok must not touch even with acceptEdits.
_DENY_RULES = (
    "Read(/**/.ssh/**)",
    "Edit(/**/.ssh/**)",
    "Write(/**/.ssh/**)",
    "Read(/**/.env)",
    "Edit(/**/.env)",
    "Write(/**/.env)",
    "Read(/**/.env.*)",
    "Edit(/**/.env.*)",
    "Write(/**/.env.*)",
    "Bash(sudo *)",
    "Bash(git push --force*)",
    "Bash(git push -f*)",
)


def grok_bin() -> Path:
    raw = os.environ.get("SOVERYN_GROK_BIN", "").strip()
    return Path(raw) if raw else DEFAULT_GROK_BIN


def grok_cwd() -> Path:
    raw = os.environ.get("SOVERYN_GROK_CWD", "").strip()
    return Path(raw) if raw else DEFAULT_CWD


def grok_timeout() -> float:
    raw = os.environ.get("SOVERYN_GROK_TIMEOUT", "").strip()
    if raw:
        try:
            return max(60.0, float(raw))
        except ValueError:
            pass
    return DEFAULT_TIMEOUT


def format_messages_for_prompt(request: ChatRequest) -> str:
    """Flatten AgentLoop messages into a single headless prompt."""
    parts: list[str] = [
        "You are Grok in SOVERYN Messages — Jon's direct coding peer on this "
        "house box. Prefer concrete file work in the allowed cwd. Be concise. "
        "Do not touch secrets (.ssh, .env), sudo, or force-push.",
        "",
    ]
    for msg in request.messages:
        role = (msg.role or "user").strip().lower()
        content = (msg.content or "").strip()
        if not content:
            continue
        if role == "system":
            parts.append(f"[system]\n{content}\n")
        elif role == "assistant":
            parts.append(f"[assistant]\n{content}\n")
        else:
            parts.append(f"[user]\n{content}\n")
    parts.append(
        "Reply to the latest user message. If coding is needed, do it, then "
        "summarize what changed."
    )
    return "\n".join(parts)


def _parse_grok_json(stdout: str) -> str:
    text = (stdout or "").strip()
    if not text:
        return ""
    # Prefer last JSON object if CLI prints noise before it.
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "text" in data:
            return str(data.get("text") or "").strip()
    except json.JSONDecodeError:
        pass
    # Find a trailing {...} block
    start = text.rfind("{")
    if start >= 0:
        try:
            data = json.loads(text[start:])
            if isinstance(data, dict) and "text" in data:
                return str(data.get("text") or "").strip()
        except json.JSONDecodeError:
            pass
    return text


def run_grok_prompt(
    prompt: str,
    *,
    cwd: Path | None = None,
    timeout: float | None = None,
    bin_path: Path | None = None,
    max_turns: int = DEFAULT_MAX_TURNS,
    tools: str | None = None,
    disallowed_tools: str | None = None,
    permission_mode: str = "acceptEdits",
    extra_flags: list[str] | None = None,
) -> str:
    """Run headless grok; return assistant text. Raises LlamaServer* on failure."""
    binary = bin_path or grok_bin()
    work = cwd or grok_cwd()
    limit = timeout if timeout is not None else grok_timeout()

    if not binary.is_file():
        raise LlamaServerError(
            status_code=503,
            detail=f"grok binary missing: {binary}",
            server_name="grok_build",
        )
    if not work.is_dir():
        raise LlamaServerError(
            status_code=503,
            detail=f"grok cwd missing: {work}",
            server_name="grok_build",
        )

    cmd: list[str] = [
        str(binary),
        "-p", prompt,
        "--cwd", str(work),
        "--output-format", "json",
        "--max-turns", str(max_turns),
        "--permission-mode", permission_mode,
    ]
    if tools:
        cmd.extend(["--tools", tools])
    if disallowed_tools:
        cmd.extend(["--disallowed-tools", disallowed_tools])
    if tools or disallowed_tools:
        cmd.append("--no-subagents")
    if extra_flags:
        cmd.extend(extra_flags)
    for rule in _DENY_RULES:
        cmd.extend(["--deny", rule])

    env = os.environ.copy()
    # Avoid nested interactive TUI / update checks during Messages turns.
    env.setdefault("GROK_NO_AUTO_UPDATE", "1")

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=limit,
            cwd=str(work),
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise LlamaServerTimeout("grok_build", limit) from exc
    except OSError as exc:
        raise LlamaServerError(
            status_code=503,
            detail=f"grok spawn failed: {exc}",
            server_name="grok_build",
        ) from exc

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        logger.warning("grok_build exit %s: %s", proc.returncode, err[:500])
        raise LlamaServerError(
            status_code=502,
            detail=f"grok exit {proc.returncode}: {err[:400] or 'no output'}",
            server_name="grok_build",
        )

    out = _parse_grok_json(proc.stdout)
    if not out:
        err = (proc.stderr or "").strip()
        raise LlamaServerError(
            status_code=502,
            detail=f"grok returned empty text{(': ' + err[:200]) if err else ''}",
            server_name="grok_build",
        )
    return out


def grok_chat(
    request: ChatRequest,
    server: ModelServer,
    timeout: float = DEFAULT_TIMEOUT,
) -> ChatResponse:
    """AgentLoop chat_fn — one headless grok turn."""
    prompt = format_messages_for_prompt(request)
    text = run_grok_prompt(prompt, timeout=timeout)
    return ChatResponse(
        content=text,
        finish_reason="stop",
        tool_calls=None,
        usage=None,
        raw={"backend": "grok_build", "server": server.name},
    )


def grok_chat_stream(
    request: ChatRequest,
    server: ModelServer,
    timeout: float = DEFAULT_TIMEOUT,
) -> Iterator[StreamChunk]:
    """AgentLoop stream_fn — run sync, then yield full text as one chunk.

    v0 prefers a correct final answer in-thread over fake token drip.
    """
    resp = grok_chat(request, server, timeout=timeout)
    yield StreamChunk(
        delta=resp.content,
        finish_reason="stop",
        tool_calls_delta=None,
        usage=resp.usage,
        raw=resp.raw,
    )
