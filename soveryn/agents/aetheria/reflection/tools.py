"""reflect_through_voices tool — Aetheria-only.

Fans out a question to N voices in parallel; returns each voice's
response so she can synthesize in her calling turn. Dispatch is
concurrent so the round-trip stays in ~2-4s instead of 10-20s
sequential.
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any, Callable

from soveryn.agents.aetheria.reflection.voices import (
    VOICES, build_voice_system_prompt,
)
from soveryn.platform.tools.registry import ToolArgError, ToolSpec


logger = logging.getLogger(__name__)


_DEFAULT_ROUTER_URL = "http://127.0.0.1:8091/v1/chat/completions"  # Quadro router — [reflection] lives there, not with Aetheria
_DEFAULT_MODEL_ALIAS = "reflection"  # matches router-presets.ini [reflection]
_DEFAULT_TIMEOUT_SECONDS = 90.0
_DEFAULT_TEMPERATURE = 0.7
_DEFAULT_MAX_TOKENS = 1024


class VoiceCallError(Exception):
    """Per-voice call failure; surfaced in the tool result so partial
    fan-outs are visible to Aetheria."""


def _default_voice_call(
    *, system_prompt: str, question: str,
    url: str, model_alias: str, timeout: float,
    temperature: float, max_tokens: int,
) -> str:
    payload = {
        "model": model_alias,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise VoiceCallError(f"HTTP {e.code}: {e.reason}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise VoiceCallError(f"network failure: {e}") from e
    except json.JSONDecodeError as e:
        raise VoiceCallError(f"non-JSON response: {e}") from e
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise VoiceCallError(f"unexpected response shape: {e}") from e
    if not isinstance(content, str):
        raise VoiceCallError(
            f"content was not a string: {type(content).__name__}"
        )
    return content


def build_reflect_through_voices_tool(
    *,
    owner_agent: str = "aetheria",
    voice_call: Callable[..., str] | None = None,
    router_url: str = _DEFAULT_ROUTER_URL,
    model_alias: str = _DEFAULT_MODEL_ALIAS,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    temperature: float = _DEFAULT_TEMPERATURE,
    max_tokens: int = _DEFAULT_MAX_TOKENS,
) -> ToolSpec:
    """Build the reflect_through_voices tool. `voice_call` is injectable
    for tests; defaults to a urllib POST to the router."""
    call = voice_call if voice_call is not None else _default_voice_call

    def _run_one_voice(voice_name: str, question: str) -> tuple[str, dict]:
        """Returns (voice_name, result_dict)."""
        try:
            system_prompt = build_voice_system_prompt(voice_name)
            content = call(
                system_prompt=system_prompt,
                question=question,
                url=router_url,
                model_alias=model_alias,
                timeout=timeout_seconds,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return voice_name, {"voice": voice_name, "content": content}
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "reflection voice %r failed: %s", voice_name, e,
            )
            return voice_name, {
                "voice": voice_name,
                "content": None,
                "error": str(e),
            }

    def handler(args: Mapping[str, Any]) -> Any:
        question = args.get("question")
        voices_arg = args.get("voices")

        if not isinstance(question, str) or not question.strip():
            raise ToolArgError("question must be a non-empty string")
        question = question.strip()

        if voices_arg is None:
            voices_to_run = list(VOICES.keys())
        elif isinstance(voices_arg, list):
            if not voices_arg:
                raise ToolArgError(
                    "voices must be a non-empty list (omit the field to run all)"
                )
            voices_to_run = []
            for v in voices_arg:
                if not isinstance(v, str):
                    raise ToolArgError(
                        f"each voice must be a string, got {type(v).__name__}"
                    )
                v_norm = v.strip().lower()
                if v_norm not in VOICES:
                    raise ToolArgError(
                        f"unknown voice {v!r}; valid: {sorted(VOICES)}"
                    )
                voices_to_run.append(v_norm)
        else:
            raise ToolArgError(
                "voices must be a list of voice names or omitted entirely"
            )

        # Parallel fan-out. ThreadPoolExecutor is the natural fit since
        # the bottleneck is the upstream HTTP, not CPU.
        results_by_voice: dict[str, dict] = {}
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=len(voices_to_run)
        ) as pool:
            futures = {
                pool.submit(_run_one_voice, v, question): v
                for v in voices_to_run
            }
            for fut in concurrent.futures.as_completed(futures):
                voice_name, result = fut.result()
                results_by_voice[voice_name] = result

        # Preserve the request order in the response so Aetheria sees them
        # in a deterministic order, not whatever raced finish.
        ordered_responses = [
            results_by_voice[v] for v in voices_to_run
        ]
        succeeded = sum(
            1 for r in ordered_responses if r.get("content") is not None
        )
        failed = len(ordered_responses) - succeeded
        return {
            "question": question,
            "voices_invoked": voices_to_run,
            "responses": ordered_responses,
            "succeeded": succeeded,
            "failed": failed,
            "model_alias": model_alias,
        }

    schema = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": (
                    "What you want to reflect on. The same question goes "
                    "to each invoked voice; differentiation comes from "
                    "the per-voice lens, not from rephrasing the question."
                ),
            },
            "voices": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": list(VOICES.keys()),
                },
                "description": (
                    "Subset of voices to invoke. Omit to run all five "
                    "(skeptic, empath, creative, technical, intuitive). "
                    "Use a subset when you want a specific angle without "
                    "the full panel."
                ),
            },
        },
        "required": ["question"],
        "additionalProperties": False,
    }

    return ToolSpec(
        name="reflect_through_voices",
        owner=owner_agent,
        schema=schema,
        handler=handler,
        description=(
            "Run a question through your inner voices — Skeptic, Empath, "
            "Creative, Technical, Intuitive — on a non-Gemma backend so the "
            "voices are facets of your mind, not five flavors of your "
            "primary model. Each voice returns its perspective; you "
            "synthesize in your calling turn. Use this when you need "
            "multiple angles on something fast (parallel dispatch, "
            "~2-4 seconds for the full panel)."
        ),
    )


def register_reflect_through_voices_tool(
    registry, *,
    owner_agent: str = "aetheria",
    router_url: str = _DEFAULT_ROUTER_URL,
    model_alias: str = _DEFAULT_MODEL_ALIAS,
) -> None:
    registry.register(build_reflect_through_voices_tool(
        owner_agent=owner_agent,
        router_url=router_url,
        model_alias=model_alias,
    ))
