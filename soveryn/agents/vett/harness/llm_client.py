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

Tool-format note: upstream's vendored ``_call_chat_completions`` calls
``toolset.get_formats(ProviderFormat.OPENAI)`` to build the ``tools=``
payload, but upstream's ``OPENAI`` format is the **Responses API** flat
shape ``{"type":"function","name":...,"parameters":...}``. The OpenAI
Chat Completions API (and llama-server's OpenAI-compat surface) require
the **nested** shape ``{"type":"function","function":{"name":...}}``,
which upstream files under ``QWEN_MOONSHOT``. We override
``_call_chat_completions`` to request the nested shape; everything else
is delegated to the parent flow.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from openai import OpenAI
from openai.types.chat import ChatCompletion, ChatCompletionMessage

from soveryn.agents.vett.harness.vendor.agent import (
    InferenceContext,
    OpenAIAgentInferenceModel,
)
from soveryn.agents.vett.harness.vendor.tools import UserTextTool
from soveryn.agents.vett.harness.vendor.trajectory import Action, ActionBuilder
from soveryn.agents.vett.harness.vendor.utils import ProviderFormat


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

    # ---- chat-completions tool-format override -------------------------------

    def _call_chat_completions(
        self, context: InferenceContext
    ) -> Optional[Action]:
        """Mirror upstream's flow, but emit Chat Completions–shaped tools.

        Upstream's ``_call_chat_completions`` requests
        ``ProviderFormat.OPENAI`` for tools, which is upstream's
        Responses-API flat shape. llama-server's chat-completions
        endpoint requires the nested shape (filed under
        ``QWEN_MOONSHOT`` in vendor/tools.py:135). We request that
        format here and otherwise replicate the parent body.
        """
        trajectory = context.trajectory
        toolset = context.toolset
        max_tokens = context.max_tokens

        request_messages = trajectory.to_provider_format(ProviderFormat.OPENAI)
        # Nested Chat Completions shape: {"type":"function","function":{...}}.
        request_tools = toolset.get_formats(ProviderFormat.QWEN_MOONSHOT)

        response: ChatCompletion = self.openai_client.chat.completions.create(
            messages=request_messages,
            tools=request_tools,  # type: ignore[arg-type]
            parallel_tool_calls=True,
            model=self.model,
            temperature=self.temperature,
            max_completion_tokens=max_tokens or self.max_output_tokens,
        )
        if not response.choices:
            raise RuntimeError("No response choices received from OpenAI")

        choice = response.choices[0]
        message: ChatCompletionMessage = choice.message
        action_builder = ActionBuilder()

        reasoning_content = getattr(message, "reasoning_content", None)
        if reasoning_content:
            action_builder.add_reasoning(reasoning_content)

        if choice.finish_reason == "stop":
            text = self._extract_chat_message_text(message)
            if text:
                action_builder.add_tool_call(UserTextTool(), {"text": text}, "agent")
        elif (
            choice.finish_reason == "tool_calls"
            and message.tool_calls
            and len(message.tool_calls) > 0
        ):
            for tool_call in message.tool_calls:
                if not hasattr(tool_call, "function"):
                    raise ValueError("Tool call is missing function payload")
                tool = toolset.get_tool(tool_call.function.name)
                if tool is None:
                    raise ValueError(
                        "Model requested unknown tool or tool not in toolset: "
                        f"{tool_call.function.name}"
                    )
                try:
                    parsed_args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"Invalid JSON arguments for tool {tool_call.function.name}"
                    ) from exc
                action_builder.add_tool_call(tool, parsed_args, tool_call.id)
        else:
            text = self._extract_chat_message_text(message)
            if text:
                action_builder.add_tool_call(UserTextTool(), {"text": text}, "agent")

        return action_builder.build()
