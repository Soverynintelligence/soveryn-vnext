"""Cognition call for the representation pass.

`run_representation_pass` builds the prompt, sends it to the reasoning
model, parses the result into Conclusions, and returns them.

Best-effort: if the cognition surface is unreachable, logs a warning and
raises CognitionFailure so the daemon can retry without consuming evidence.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Callable

from soveryn.agents.representation.parse import Conclusion, parse_conclusions
from soveryn.agents.representation.prompt import render_representation_prompt

_log = logging.getLogger(__name__)

# Default timeout (seconds) for the HTTP call to the cognition surface.
_TIMEOUT = 180
_MAX_ATTEMPTS = 2
MAX_OUTPUT_TOKENS = 1024
MAX_PROMPT_BYTES = 10_000


class CognitionFailure(RuntimeError):
    """Failed request; caller must retain its processed-turn cursor."""



def _default_chat_fn(prompt: str, cognition_url: str) -> str:
    """POST prompt to <cognition_url>/v1/chat/completions and return content.

    Mirrors the shape of dream.cognition.chat_completion exactly:
    - method  : POST
    - url     : <cognition_url>/v1/chat/completions
    - model   : "dream"  (served-model alias on the cognition surface / :8089)
    - timeout : 180 s
    """
    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "model": "dream",
        # Low temperature: representation reasoning should be steady/repeatable,
        # not creative. (Gate finding 2026-06-17: temp 0.7 gave 0 conclusions on
        # one call, 3 on the next from identical input.)
        "temperature": 0.3,
        "max_tokens": MAX_OUTPUT_TOKENS,
    }
    body = json.dumps(payload).encode()
    full_url = cognition_url.rstrip("/") + "/v1/chat/completions"
    req = urllib.request.Request(
        full_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        data = json.loads(resp.read())
    content = data["choices"][0]["message"]["content"]
    if not isinstance(content, str):
        raise ValueError(f"content was not a string: {type(content).__name__}")
    return content


def run_representation_pass(
    *,
    subject: str,
    briefing: str,
    prior_conclusions: str,
    cognition_url: str,
    chat_fn: Callable[[str, str], str] | None = None,
    diagnostics: dict | None = None,
) -> list[Conclusion]:
    """Build the representation prompt, call the cognition model, parse results.

    Parameters
    ----------
    subject:
        The entity being represented (e.g. a user name).
    briefing:
        Recent witness-node lines, each prefixed with ``[node:ID]``.
    prior_conclusions:
        Prior conclusion-node lines, each prefixed with ``[node:ID]``.
    cognition_url:
        Base URL for the cognition surface (e.g. ``http://localhost:8089``).
    chat_fn:
        Optional override for the HTTP call.  Signature:
        ``(prompt: str, cognition_url: str) -> str``.  Defaults to
        ``_default_chat_fn``.  Inject a fake in tests so no real HTTP happens.

    Returns
    -------
    list[Conclusion]
        Parsed conclusions.  Raises CognitionFailure after bounded retries if the request fails.
    """
    if chat_fn is None:
        chat_fn = _default_chat_fn

    prompt = render_representation_prompt(
        subject=subject,
        briefing=briefing,
        prior_conclusions=prior_conclusions,
    )

    raw = request_text(prompt, cognition_url, chat_fn=chat_fn)
    conclusions = parse_conclusions(raw)
    if diagnostics is not None:
        diagnostics.update(response_chars=len(raw), parsed=len(conclusions))
        if not conclusions:
            diagnostics["empty_result_excerpt"] = raw[:600]
    _log.info("representation cognition response: chars=%d parsed=%d", len(raw), len(conclusions))
    return conclusions


def request_text(prompt: str, cognition_url: str, *, chat_fn=None) -> str:
    """Bounded text-only cognition call shared by the two Forge extractors."""
    chat_fn = chat_fn or _default_chat_fn
    if len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
        raise CognitionFailure("prompt exceeds conservative 10K byte budget")
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        retryable = True
        try:
            raw = chat_fn(prompt, cognition_url)
            break
        except urllib.error.HTTPError as exc:
            # Bounded response excerpt exposes the actual reason for 400s.
            detail = exc.read(2048).decode("utf-8", errors="replace")
            _log.warning("representation cognition HTTP status=%s body=%r attempt=%d/%d",
                         exc.code, detail, attempt, _MAX_ATTEMPTS)
            retryable = exc.code == 429 or exc.code >= 500
            failure = exc
        except Exception as exc:
            _log.warning("representation cognition failed: %s attempt=%d/%d",
                         exc, attempt, _MAX_ATTEMPTS)
            failure = exc
        if not retryable or attempt == _MAX_ATTEMPTS:
            raise CognitionFailure("representation cognition request failed") from failure
        time.sleep(0.5)
    if not isinstance(raw, str):
        raise CognitionFailure("model content was not a string")
    return raw
