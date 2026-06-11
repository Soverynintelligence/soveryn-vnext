"""SOVERYN inference-model shim for the vendored harness.

Subclasses the vendored ``OpenAIAgentInferenceModel`` and points its
OpenAI client at our llama-server router (OpenAI-compat layer). No
behavioral changes — we inherit prompt assembly, tool-call parsing,
and the ``__call__`` flow from upstream.

The upstream default is the Responses API (``api_style="responses"``)
which is tuned for OpenAI's gpt-* models; llama-server only serves
chat-completions, so we pin ``api_style="chat_completions"``. Task 3's
format-compat probe proved Vett (Qwen3.6-27B on :8090) accepts that
shape.
"""
from __future__ import annotations

from openai import OpenAI

from soveryn.agents.vett.harness.vendor.agent import OpenAIAgentInferenceModel


_DEFAULT_ROUTER_URL = "http://127.0.0.1:8090"
_DEFAULT_MODEL = "vett-scotty"


class SoverynVettInferenceModel(OpenAIAgentInferenceModel):
    """Vett's LLM client for the vendored harness.

    Targets the llama-server router at :8090, model=vett-scotty.
    Uses the chat-completions API path; avoids token-level coupling
    with gpt-oss-20b's tokenizer.
    """

    def __init__(
        self,
        *,
        router_url: str = _DEFAULT_ROUTER_URL,
        model_name: str = _DEFAULT_MODEL,
        max_output_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> None:
        # llama-server's OpenAI-compat layer doesn't enforce API keys;
        # the OpenAI SDK still requires a non-empty string at construct time.
        client = OpenAI(base_url=f"{router_url}/v1", api_key="not-used")
        super().__init__(
            openai_client=client,
            model=model_name,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            api_style="chat_completions",
        )
