"""Cognition call for the representation pass.

`run_representation_pass` builds the prompt, sends it to the reasoning
model, parses the result into Conclusions, and returns them.

Best-effort: if the cognition surface is unreachable, logs a warning and
returns an empty list — never crashes the daemon.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from collections.abc import Callable

from soveryn.agents.representation.parse import Conclusion, parse_conclusions
from soveryn.agents.representation.prompt import render_representation_prompt

_log = logging.getLogger(__name__)

# Default timeout (seconds) for the HTTP call to the cognition surface.
_TIMEOUT = 60


def _default_chat_fn(prompt: str, cognition_url: str) -> str:
    """POST prompt to <cognition_url>/v1/chat/completions and return content.

    Mirrors the shape of dream.cognition.chat_completion exactly:
    - method  : POST
    - url     : <cognition_url>/v1/chat/completions
    - model   : "dream"  (served-model alias on the cognition surface / :8089)
    - timeout : 60 s
    """
    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "model": "dream",
        "temperature": 0.7,
        "max_tokens": 2048,
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
        Parsed conclusions.  Returns ``[]`` if the cognition surface raises.
    """
    if chat_fn is None:
        chat_fn = _default_chat_fn

    prompt = render_representation_prompt(
        subject=subject,
        briefing=briefing,
        prior_conclusions=prior_conclusions,
    )

    try:
        raw = chat_fn(prompt, cognition_url)
    except Exception as exc:  # best-effort: never crash the daemon
        _log.warning("representation cognition call failed: %s", exc)
        return []

    return parse_conclusions(raw)
