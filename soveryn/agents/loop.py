"""SOVERYN vNext — minimal AgentLoop.

First behavior-bearing module. Orchestrates one chat turn:

  1. Validate session exists and belongs to this agent.
  2. Save user turn to conversation_store.
  3. Load history (now including the just-saved user turn).
  4. Build ChatRequest with history as immutable tuple[ChatMessage, ...].
  5. Call chat_fn(request, server, timeout).
  6. Save assistant turn from response.content (content only — raw metadata
     stays on the returned ChatResponse for the caller).
  7. Return the raw ChatResponse.

Out of scope this commit:
  - system prompts / personas / prompt templating
  - tool calling and dispatch
  - memory recall (Lattice queries injected into context)
  - streaming
  - think-block stripping / response finalization
  - history windowing / token-budget management

Routing is the trust boundary (Jon constraint 1): route_for_agent runs
at construction so AgentLoop("scout", ...) fails immediately, never at
turn-processing time.
"""

from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

from soveryn.agents.personas import get_persona
from soveryn.agents.aetheria.speech_assembler import assemble_ranked_recall
from soveryn.agents.souls import get_soul
from soveryn.inference.llama_server_client import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    LlamaServerError,
    LlamaServerTimeout,
    StreamChunk,
    chat as _default_chat,
    chat_stream as _default_chat_stream,
)
from soveryn.inference.routing import route_for_agent
from soveryn.memory.conversation_store import ConversationStore
from soveryn.memory.lattice import LatticeStore, Node, embed_text as _default_embed
from soveryn.platform.continuity.config import ContinuityConfig
from soveryn.platform.tools.registry import ToolArgError, ToolRegistry
from soveryn.platform.voice.sanitize import sanitize_for_tts


ChatFn = Callable[..., ChatResponse]
EmbedFn = Callable[[str], tuple[float, ...]]
StreamFn = Callable[..., Iterator[StreamChunk]]


# ─────────────────────────────────────────────────────────────────────────────
# Stream event types
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TokenEvent:
    """One content delta from the stream."""
    delta: str


@dataclass(frozen=True)
class DoneEvent:
    """Stream completed normally. Carries accumulated content + finish_reason."""
    content: str
    finish_reason: str
    tool_calls: tuple[dict, ...] | None
    usage: dict | None
    # Populated by AgentLoop when history_token_budget is active. Same shape
    # as ChatResponse.context_usage so /chat_stream and /chat agree.
    context_usage: dict | None = None


@dataclass(frozen=True)
class ErrorEvent:
    """Stream failed. NO assistant turn was saved when this event fires."""
    code: str
    message: str


@dataclass(frozen=True)
class ToolCallEvent:
    """The model finalized a tool_call mid-stream. Emitted before invocation
    so the UI can show "Aetheria is using tool X" while the handler runs.

    args: the JSON-string args as the model produced them. The UI gets the raw
    string; structured parsing happens at the registry boundary.
    """
    call_id: str
    name: str
    args: str


@dataclass(frozen=True)
class ToolResultEvent:
    """A tool handler returned. Emitted after the result has been rendered
    through classify_and_render so channel-aware framing is preserved.

    channel: "A" (witnessed content) or "B" (count-only / uncertain) — lets the
    UI style the result differently so Channel B doesn't masquerade as a
    grounded retrieval. Optional for callers that don't classify.
    """
    call_id: str
    name: str
    content: str
    channel: str | None = None


@dataclass(frozen=True)
class TTSTokenEvent:
    """Sanitized assistant text fragment for TTS consumption.

    Emitted alongside regular TokenEvent in process_message_stream so voice
    consumers see only clean prose (no thinking, markup, control tokens,
    etc.). Chat UI consumers ignore this event; voice pipeline consumers
    subscribe to it instead of TokenEvent.

    Sanitization at source — single boundary, not a downstream filter
    cascade. Replaces the accumulated filter chain from the legacy voice
    pipeline. Skipped entirely when the sanitized text would be empty
    (the chunk was pure markup / control tokens / emoji).
    """
    text: str


# Union type alias for typing
AgentStreamEvent = (
    TokenEvent | DoneEvent | ErrorEvent | ToolCallEvent | ToolResultEvent
    | TTSTokenEvent
)


# ─────────────────────────────────────────────────────────────────────────────
# Tool-call accumulation helper
# ─────────────────────────────────────────────────────────────────────────────

def _accumulate_tool_calls(
    accumulated: list[dict],
    delta_list: list,
) -> list[dict]:
    """Merge OpenAI-format tool_call deltas into the accumulator (by index).

    OpenAI streams tool_calls as deltas keyed by `index`. Each delta may carry
    partial id, type, function.name, function.arguments — we merge them
    positionally. Mutates `accumulated` in place and returns it for chaining.
    """
    for d in delta_list:
        if not isinstance(d, dict):
            continue
        idx = d.get("index", 0)
        # Ensure the slot exists
        while len(accumulated) <= idx:
            accumulated.append({"index": len(accumulated), "function": {"name": "", "arguments": ""}})
        slot = accumulated[idx]
        if "id" in d and d["id"]:
            slot["id"] = d["id"]
        if "type" in d and d["type"]:
            slot["type"] = d["type"]
        fn_delta = d.get("function") or {}
        if isinstance(fn_delta, dict):
            if fn_delta.get("name"):
                slot["function"]["name"] = slot["function"].get("name", "") + fn_delta["name"]
            if "arguments" in fn_delta:
                slot["function"]["arguments"] = slot["function"].get("arguments", "") + (fn_delta.get("arguments") or "")
    return accumulated


# ─────────────────────────────────────────────────────────────────────────────
# History budgeter — char/4 estimator + trim helper
# ─────────────────────────────────────────────────────────────────────────────

_PER_MESSAGE_OVERHEAD_TOKENS = 5
# Conservative ballpark for a single image's contribution to the prompt token
# count. Real Gemma 4 mmproj cost is ~256 tokens per image at default
# resolution; over-estimating is the safe direction for budget-trim decisions
# (we'd rather trim slightly aggressively than fail to trim and overflow).
_PER_IMAGE_TOKEN_COST = 512


def _estimate_tokens(text: str) -> int:
    """Char/4 ballpark. Actual token count comes back from llama-server's
    usage.prompt_tokens post-call; this estimator only drives trim decisions."""
    return max(1, len(text or "") // 4)


def _estimate_message_tokens(msg: ChatMessage) -> int:
    """Per-message estimate with small overhead for role/structure framing.

    Handles both str-content (plain text) and list-content (OpenAI vision
    parts, after SI-T1's ChatMessage.content widening). For list content,
    each text part contributes len/4 tokens and each image_url part
    contributes _PER_IMAGE_TOKEN_COST. A naive len(list) would treat a
    multimodal turn as ~1 token and break history-budget trim logic on
    vision turns.
    """
    content = msg.content
    if isinstance(content, str):
        return _estimate_tokens(content) + _PER_MESSAGE_OVERHEAD_TOKENS
    # list[dict] — sum text-part chars (//4) + per-image cost. Unknown part
    # shapes contribute nothing; the structure overhead is captured by the
    # per-message overhead constant.
    text_tokens = 0
    image_tokens = 0
    for part in content:
        if not isinstance(part, dict):
            continue
        ptype = part.get("type")
        if ptype == "text":
            text_tokens += _estimate_tokens(part.get("text", ""))
        elif ptype == "image_url":
            image_tokens += _PER_IMAGE_TOKEN_COST
    return text_tokens + image_tokens + _PER_MESSAGE_OVERHEAD_TOKENS


def _apply_history_budget(
    prelude: tuple[ChatMessage, ...],
    history: tuple[ChatMessage, ...],
    budget: int,
) -> tuple[tuple[ChatMessage, ...], ChatMessage | None, int]:
    """Drop oldest history turns until prelude + history fits inside budget.

    Always preserves history[-1] (the just-saved user message). Returns:
      (possibly_trimmed_history, elision_marker_or_None, elided_count)

    If the most recent turn alone (plus prelude) already blows the budget,
    that's a prompt-overflow condition the budgeter can't fix — we still
    drop everything older and surface the overflow via context_usage so the
    UI banner reflects it.
    """
    if not history:
        return history, None, 0
    prelude_tokens = sum(_estimate_message_tokens(m) for m in prelude)
    history_tokens = [_estimate_message_tokens(m) for m in history]
    total = prelude_tokens + sum(history_tokens)
    if total <= budget:
        return history, None, 0

    kept = list(history)
    kept_tokens = list(history_tokens)
    dropped = 0
    while len(kept) > 1 and total > budget:
        total -= kept_tokens.pop(0)
        kept.pop(0)
        dropped += 1
    if dropped == 0:
        return history, None, 0
    marker = ChatMessage(
        role="system",
        content=f"[Context: {dropped} older turn(s) elided to fit token budget.]",
    )
    return tuple(kept), marker, dropped


class AgentLoopError(Exception):
    """Raised by AgentLoop on session validation or contract violations."""


class AgentLoop:
    """Single-turn orchestrator for one named agent.

    Constructor binds to one agent + one model server. Routing happens
    once at construction; subsequent turns reuse the resolved server.
    Tests inject a fake `chat_fn`; production uses the default.
    """

    def __init__(
        self,
        agent_name: str,
        conv_store: ConversationStore,
        chat_fn: ChatFn = _default_chat,
        stream_fn: StreamFn = _default_chat_stream,
        chat_timeout_seconds: float = 120.0,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        thinking_budget_tokens: int | None = None,
        history_token_budget: int | None = None,
        context_window: int | None = None,
        tool_registry: ToolRegistry | None = None,
        max_tool_rounds: int = 4,
        system_prompt: str | None = None,
        lattice_store: LatticeStore | None = None,
        identity_spine_store: LatticeStore | None = None,
        recall_k: int = 0,
        recall_threshold: float = 0.70,
        embed_fn: EmbedFn = _default_embed,
        soul_text: str | None = "",
        souls_dir: Path | None = None,
        pinned_text: str = "",
        continuity_config: ContinuityConfig | None = None,
    ) -> None:
        self.agent_name = agent_name.lower().strip()
        # Route at construction — RoutingError on unknown/retired names
        # bubbles up here, NEVER at turn-processing time.
        self.server = route_for_agent(self.agent_name)
        self.conv_store = conv_store
        self.chat_fn = chat_fn
        self.stream_fn = stream_fn
        self.chat_timeout_seconds = chat_timeout_seconds
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.thinking_budget_tokens = thinking_budget_tokens
        # History budget: when set, oldest history turns are dropped before
        # building the request until estimated tokens fit. Surfaced via
        # context_usage on ChatResponse/DoneEvent so the UI can warn at ≥85%
        # of context_window before forced trimming. None = unlimited (Vett,
        # Scotty, tests). context_window is the underlying server's max
        # context — used by the UI as the denominator for the pressure bar,
        # not enforced here.
        if history_token_budget is not None and history_token_budget <= 0:
            raise ValueError(
                f"history_token_budget must be > 0 if set (got {history_token_budget})"
            )
        if context_window is not None and context_window <= 0:
            raise ValueError(
                f"context_window must be > 0 if set (got {context_window})"
            )
        self.history_token_budget = history_token_budget
        self.context_window = context_window
        self.tool_registry = tool_registry
        self.max_tool_rounds = max_tool_rounds
        # Tri-state per Jon:
        #   None         → load default persona for this agent
        #   non-empty    → use as system message
        #   empty string → NO system message (skip the system turn)
        if system_prompt is None:
            self.system_prompt: str = get_persona(self.agent_name)
        else:
            self.system_prompt = system_prompt

        # Recall is opt-in. Validate the trio.
        if recall_k < 0:
            raise ValueError(f"recall_k must be >= 0 (got {recall_k})")
        if recall_k > 0:
            if lattice_store is None:
                raise ValueError(
                    "recall_k > 0 requires lattice_store; "
                    "pass a LatticeStore instance or set recall_k=0"
                )
            if not (0.0 < recall_threshold <= 1.0):
                raise ValueError(
                    f"recall_threshold must be in (0.0, 1.0] when recall is enabled "
                    f"(got {recall_threshold})"
                )
        self.lattice_store = lattice_store
        self.identity_spine_store = identity_spine_store
        self.recall_k = recall_k
        self.recall_threshold = recall_threshold
        self.embed_fn = embed_fn

        # Tri-state per Jon (parallel to system_prompt's tri-state):
        #   ""           → SKIP soul (no soul system message). Tests rely on this default.
        #   None         → LOAD soul via get_soul() — raises SoulMissingError if file missing.
        #   non-empty    → USE the given string as soul content.
        if soul_text is None:
            self.soul_text: str = get_soul(self.agent_name, souls_dir=souls_dir)
        else:
            self.soul_text = soul_text

        # Pinned memory is Aetheria's relationship substrate (third identity
        # layer between persona and soul). Default empty = skip — Vett and
        # Scotty rely on this. Production opts Aetheria in via startup.py.
        self.pinned_text: str = pinned_text

        # Cross-Surface Continuity (Aetheria-only). None = disabled; the
        # helper short-circuits to "" so non-aetheria loops never pay any
        # query cost.
        self.continuity_config = continuity_config

    def _build_continuity_brief(self, session_id: str) -> str:
        """Build the Cross-Surface Recent Activity Brief for this turn.

        Returns '' when continuity is off, the agent isn't Aetheria, the
        current session is autonomous (heartbeat/dream/patrol/webhook/
        salience-smoke), there's no cross-session activity in the window,
        or any error fires during brief computation. Never raises — chat
        path correctness is the priority.
        """
        if self.continuity_config is None or not self.continuity_config.enabled:
            return ""
        if self.agent_name != "aetheria":
            return ""
        try:
            session = self.conv_store.get_session(session_id)
            if session is not None and self.continuity_config.session_is_autonomous(session.title):
                return ""
            from soveryn.platform.continuity.store import recent_cross_session_tails
            from soveryn.platform.continuity.brief import build_recent_activity_brief
            tails = recent_cross_session_tails(
                self.conv_store,
                agent=self.agent_name,
                current_session_id=session_id,
                config=self.continuity_config,
            )
            return build_recent_activity_brief(tails, config=self.continuity_config)
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                "continuity brief build failed; serving without it"
            )
            return ""

    def _tool_schemas(self) -> tuple[dict, ...]:
        """Return OpenAI-compatible tool schemas for this agent."""

        if self.tool_registry is None:
            return ()
        schemas: list[dict] = []
        for spec in self.tool_registry.iter_tools_for_agent(self.agent_name):
            schemas.append({
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": dict(spec.schema),
                },
            })
        return tuple(schemas)

    def process_message(
        self,
        session_id: str,
        user_message: str,
        attachments: tuple[str, ...] | None = None,
    ) -> ChatResponse:
        """Run one turn. Returns the raw ChatResponse.

        attachments — when non-empty, the current (last) user message's
        wire-level content is replaced with an OpenAI vision-format list
        ([{"type": "text", ...}, {"type": "image_url", ...}, ...]). The DB
        row still stores `user_message` as plain text (no schema migration;
        multimodal history persistence is intentionally deferred). Aetheria
        is the only agent with a vision-capable model loaded — passing
        attachments to any other agent raises AgentLoopError BEFORE
        save_turn so guard rejections don't pollute history with a phantom
        user turn.

        Raises:
          AgentLoopError — session does not exist OR session.agent != self.agent_name
                           OR attachments passed to a non-aetheria agent
                           (in all cases, NO user turn is saved, NO chat dispatched)
          ConversationStoreError — invalid role on save (shouldn't happen here)
          LlamaServerError / LlamaServerTimeout — chat failure (user turn stays saved)
          sqlite3.* — DB error during turn save (propagates, no swallowing)
        """
        # Constraint 8 — validate session ownership BEFORE any side effects.
        session = self.conv_store.get_session(session_id)
        if session is None:
            raise AgentLoopError(
                f"session_id={session_id!r} does not exist; "
                "call conv_store.new_session() first"
            )
        if session.agent != self.agent_name:
            raise AgentLoopError(
                f"session {session_id!r} belongs to agent {session.agent!r}, "
                f"not {self.agent_name!r}"
            )

        # Vision guard — BEFORE save_turn so a rejected attachment leaves no
        # phantom user turn behind. Aetheria is the only agent with a
        # vision-capable model loaded; routing other agents' attachments
        # would silently drop the image at the wire boundary.
        if attachments and self.agent_name != "aetheria":
            raise AgentLoopError(
                f"attachments only supported for aetheria "
                f"(agent {self.agent_name!r} has no vision model loaded)"
            )

        # 1. Save user turn (constraint 6: stays saved if chat later fails).
        # Text-only by design — vision parts live in-flight, not in the DB.
        self.conv_store.save_turn(session_id, self.agent_name, "user", user_message)

        # 2. Load history (includes the just-saved user turn).
        history_turns = self.conv_store.load_history(session_id)

        # Recall context: opt-in. When enabled, embed the user message,
        # query Lattice for nearest-K nodes, format into a second system
        # message. Failures propagate (Jon constraint 7): if you opted
        # into recall, you own its infrastructure.
        recall_context: str = ""
        if self.recall_k > 0:
            query_vector = self.embed_fn(user_message)
            ranked = self.lattice_store.find_nodes_by_embedding(
                self.agent_name,
                query_vector,
                limit=self.recall_k,
                threshold=self.recall_threshold,
            )
            recall_context = assemble_ranked_recall(
                ranked,
                identity_nodes=_identity_spine_nodes(self.identity_spine_store, agent=self.agent_name),
            )

        # 3. Build immutable tuple[ChatMessage, ...] (constraint 7).
        # System message is prepended at request build time — NOT persisted
        # to conversations table. Empty system_prompt means skip it entirely.
        history_messages = tuple(
            ChatMessage(role=t.role, content=t.content) for t in history_turns
        )
        prelude: tuple[ChatMessage, ...] = ()
        # Semantic layers (persona / pinned / soul / recall+spine) are kept
        # separate at the AgentLoop level regardless of model. The transport
        # adapter `prepare_wire_messages` (in llama_server_client.py) folds
        # them into one system message at the HTTP boundary if the target
        # server's chat template can't honor multiple system messages.
        # See project_soveryn_qwen36_multisystem_drop +
        # project_soveryn_three_tracks_workaround_capability_agency.
        if self.system_prompt:
            prelude = prelude + (ChatMessage(role="system", content=self.system_prompt),)
        # Cross-Surface Continuity: slot between persona-anchor and
        # long-term-relationship pinned memory. Empty when not applicable.
        continuity_brief = self._build_continuity_brief(session_id)
        if continuity_brief:
            prelude = prelude + (ChatMessage(role="system", content=continuity_brief),)
        if self.pinned_text:
            prelude = prelude + (ChatMessage(role="system", content=self.pinned_text),)
        if self.soul_text:
            prelude = prelude + (ChatMessage(role="system", content=self.soul_text),)
        if recall_context:
            prelude = prelude + (ChatMessage(role="system", content=recall_context),)

        elided_turns = 0
        if self.history_token_budget is not None:
            history_messages, marker, elided_turns = _apply_history_budget(
                prelude, history_messages, self.history_token_budget,
            )
            if marker is not None:
                prelude = prelude + (marker,)
        messages: tuple[ChatMessage, ...] = prelude + history_messages

        # Vision splice — replace the current (last) user message's content
        # with an OpenAI vision-format list when attachments are present.
        # Splice happens AFTER _apply_history_budget so the budgeter (which
        # only ever sees str-content history) doesn't have to know about the
        # in-flight image cost. The DB save above is unaffected.
        if attachments:
            last = messages[-1]
            assert last.role == "user", (
                "last message must be the current user turn when splicing attachments"
            )
            spliced_content: list[dict] = [{"type": "text", "text": user_message}]
            for url in attachments:
                spliced_content.append({"type": "image_url", "image_url": {"url": url}})
            messages = messages[:-1] + (
                ChatMessage(role="user", content=spliced_content),
            )

        # 4. Dispatch chat. Any failure propagates; user turn is already saved.
        request = ChatRequest(
            messages=messages,
            model=self.server.model_alias,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            tools=self._tool_schemas() or None,
            thinking_budget_tokens=self.thinking_budget_tokens,
        )
        response = self.chat_fn(request, self.server, timeout=self.chat_timeout_seconds)

        tool_rounds = 0
        while response.tool_calls and self.tool_registry is not None:
            if tool_rounds >= self.max_tool_rounds:
                response = ChatResponse(
                    content=response.content,
                    finish_reason="tool_round_limit",
                    tool_calls=response.tool_calls,
                    usage=response.usage,
                    raw=response.raw,
                )
                break
            messages = messages + (ChatMessage(
                role="assistant",
                content=response.content,
                tool_calls=response.tool_calls,
            ),)
            messages = messages + tuple(
                self._tool_result_message(tool_call)
                for tool_call in response.tool_calls
            )
            request = ChatRequest(
                messages=messages,
                model=self.server.model_alias,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                tools=self._tool_schemas() or None,
                thinking_budget_tokens=self.thinking_budget_tokens,
            )
            response = self.chat_fn(request, self.server, timeout=self.chat_timeout_seconds)
            tool_rounds += 1

        # 5. Save assistant turn from response.content ONLY (constraint 4).
        #    Any DB error here propagates (constraint 5) — we don't pretend
        #    success. Three classes of failure are caught loudly here so the
        #    caller (Flask route → user, or webhook dispatcher → audit) sees
        #    them instead of getting a silently-saved empty turn:
        #
        #      (a) tool_round_limit: the loop hit max_tool_rounds with the
        #          model still wanting tools. The 2026-06-04 evening probe
        #          confirmed this class of failure was structurally invisible
        #          — Vett emitted 4 rounds of web_search calls trying to work
        #          through a 7-source Blueprint, hit the cap, and his empty
        #          content got persisted with no error surfaced anywhere.
        #      (b) empty content + no tool_calls: the model produced literal
        #          silence with no plan to continue. Same poisoning risk as
        #          the streaming path's existing guard.
        #
        # Both raise AgentLoopError. The /chat route translates to 500 with
        # the message; the user / dispatcher sees the actual failure mode.
        if response.finish_reason == "tool_round_limit" and not response.content:
            raise AgentLoopError(
                f"tool_round_limit: model exhausted the {self.max_tool_rounds}-round "
                f"tool budget without emitting visible content. Reduce task scope or "
                f"raise max_tool_rounds. No assistant turn saved."
            )
        if not response.content and not response.tool_calls:
            raise AgentLoopError(
                f"empty_generation: model produced no visible content "
                f"(finish_reason={response.finish_reason}); no assistant turn saved"
            )
        self.conv_store.save_turn(
            session_id, self.agent_name, "assistant", response.content,
            finish_reason=response.finish_reason,
        )

        # 6. Return raw ChatResponse (constraint 3). When a history budget is
        # active, decorate with context_usage so the UI can show pressure.
        if self.history_token_budget is not None:
            response = ChatResponse(
                content=response.content,
                finish_reason=response.finish_reason,
                tool_calls=response.tool_calls,
                usage=response.usage,
                raw=response.raw,
                context_usage=self._build_context_usage(response.usage, elided_turns),
            )
        return response

    def _build_context_usage(
        self, usage: dict | None, elided_turns: int,
    ) -> dict:
        """Build the context_usage payload returned alongside a ChatResponse.

        prompt_tokens comes from the model's reported usage when available;
        if the server didn't return usage (e.g. a fake_chat in tests), we
        fall back to 0 so the UI math is defined.
        """
        prompt_tokens = 0
        if isinstance(usage, dict):
            try:
                prompt_tokens = int(usage.get("prompt_tokens") or 0)
            except (TypeError, ValueError):
                prompt_tokens = 0
        return {
            "prompt_tokens": prompt_tokens,
            "budget_tokens": self.history_token_budget,
            "elided_turns": elided_turns,
            "context_window": self.context_window,
        }

    def _tool_result_message(self, tool_call: dict) -> ChatMessage:
        call_id = str(tool_call.get("id") or "")
        function = tool_call.get("function") or {}
        tool_name = str(function.get("name") or "")
        raw_args = function.get("arguments") or "{}"
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
        except (TypeError, json.JSONDecodeError) as exc:
            result = {"error": "ToolArgError", "message": str(exc)}
        else:
            try:
                result = self.tool_registry.invoke(self.agent_name, tool_name, args)
            except ToolArgError as exc:
                result = {"error": "ToolArgError", "message": str(exc)}
            except Exception as exc:  # noqa: BLE001 — handler failures must surface
                # Any other tool handler exception (DB lock, transient network,
                # bug in a tool) becomes a tool-result payload the model can
                # see and respond to. Without this, a single tool handler raise
                # crashes the whole turn. BaseException stays unhandled —
                # SystemExit / KeyboardInterrupt propagate as intended.
                result = {"error": type(exc).__name__, "message": str(exc)}
        return ChatMessage(
            role="tool",
            content=json.dumps(result, sort_keys=True),
            tool_call_id=call_id,
        )

    def process_message_stream(
        self,
        session_id: str,
        user_message: str,
        attachments: tuple[str, ...] | None = None,
    ) -> "Iterator[AgentStreamEvent]":
        """Streaming variant. Yields TokenEvent per content delta, then either
        DoneEvent (success) or ErrorEvent (mid-stream failure). Assistant turn
        saved ONLY on DoneEvent, AND only if upstream sent an explicit
        finish_reason (constraint 5).

        attachments — mirror of process_message: wire-level current user
        message becomes a vision-format list; DB still stores text-only;
        aetheria-only (raises AgentLoopError BEFORE save_turn otherwise).

        Setup errors (session validation, recall failures, LlamaServerError
        BEFORE the first chunk) propagate as exceptions — the Flask route
        translates those to JSON 5xx before opening SSE. Errors AFTER the
        first chunk are caught here and yielded as ErrorEvent.
        """
        # ── Session validation (BEFORE any side effect, same as sync path)
        session = self.conv_store.get_session(session_id)
        if session is None:
            raise AgentLoopError(
                f"session_id={session_id!r} does not exist; "
                "call conv_store.new_session() first"
            )
        if session.agent != self.agent_name:
            raise AgentLoopError(
                f"session {session_id!r} belongs to agent {session.agent!r}, "
                f"not {self.agent_name!r}"
            )

        # Vision guard — BEFORE save_turn so a rejected attachment leaves no
        # phantom user turn behind. Mirrors the sync path.
        if attachments and self.agent_name != "aetheria":
            raise AgentLoopError(
                f"attachments only supported for aetheria "
                f"(agent {self.agent_name!r} has no vision model loaded)"
            )

        # ── Save user turn FIRST (honest state if stream fails later).
        # Text-only by design — vision parts live in-flight, not in the DB.
        self.conv_store.save_turn(session_id, self.agent_name, "user", user_message)
        history_turns = self.conv_store.load_history(session_id)

        # ── Recall (opt-in; same as sync). Failures propagate — route turns into JSON 5xx.
        recall_context: str = ""
        if self.recall_k > 0:
            query_vector = self.embed_fn(user_message)
            ranked = self.lattice_store.find_nodes_by_embedding(
                self.agent_name, query_vector,
                limit=self.recall_k, threshold=self.recall_threshold,
            )
            recall_context = assemble_ranked_recall(
                ranked,
                identity_nodes=_identity_spine_nodes(self.identity_spine_store, agent=self.agent_name),
            )

        # ── Build messages
        history_messages = tuple(
            ChatMessage(role=t.role, content=t.content) for t in history_turns
        )
        prelude: tuple[ChatMessage, ...] = ()
        # Same as sync path — semantic layers stay separate; transport adapter
        # folds at wire if the server's template can't honor multi-system.
        if self.system_prompt:
            prelude = prelude + (ChatMessage(role="system", content=self.system_prompt),)
        # Cross-Surface Continuity: same placement as the sync path —
        # between persona and pinned memory. Empty when not applicable.
        continuity_brief = self._build_continuity_brief(session_id)
        if continuity_brief:
            prelude = prelude + (ChatMessage(role="system", content=continuity_brief),)
        if self.pinned_text:
            prelude = prelude + (ChatMessage(role="system", content=self.pinned_text),)
        if self.soul_text:
            prelude = prelude + (ChatMessage(role="system", content=self.soul_text),)
        if recall_context:
            prelude = prelude + (ChatMessage(role="system", content=recall_context),)

        elided_turns = 0
        if self.history_token_budget is not None:
            history_messages, marker, elided_turns = _apply_history_budget(
                prelude, history_messages, self.history_token_budget,
            )
            if marker is not None:
                prelude = prelude + (marker,)
        messages = prelude + history_messages

        # Vision splice — replace the current (last) user message's content
        # with an OpenAI vision-format list when attachments are present.
        # Same logic as process_message; happens AFTER _apply_history_budget
        # (which only ever sees str-content history) and BEFORE the round
        # loop opens so the spliced message participates in every retry.
        if attachments:
            last = messages[-1]
            assert last.role == "user", (
                "last message must be the current user turn when splicing attachments"
            )
            spliced_content: list[dict] = [{"type": "text", "text": user_message}]
            for url in attachments:
                spliced_content.append({"type": "image_url", "image_url": {"url": url}})
            messages = messages[:-1] + (
                ChatMessage(role="user", content=spliced_content),
            )

        # Round loop: streaming generation → maybe tool calls → tool dispatch →
        # next streaming generation, until the model emits a final answer or we
        # hit max_tool_rounds. Mirrors the sync-path semantics in
        # process_message.
        tool_rounds = 0
        final_content_parts: list[str] = []
        final_finish_reason: str | None = None
        final_usage: dict | None = None

        while True:
            request = ChatRequest(
                messages=messages,
                model=self.server.model_alias,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                tools=self._tool_schemas() or None,
                thinking_budget_tokens=self.thinking_budget_tokens,
            )

            # ── Open the stream. PRE-stream errors propagate (route → JSON 5xx).
            chunk_iter = self.stream_fn(request, self.server, timeout=self.chat_timeout_seconds)

            round_content_parts: list[str] = []
            round_tool_calls: list[dict] = []
            round_finish_reason: str | None = None
            first_chunk_seen = False

            try:
                for chunk in chunk_iter:
                    first_chunk_seen = True
                    if chunk.delta:
                        round_content_parts.append(chunk.delta)
                        yield TokenEvent(delta=chunk.delta)
                        # Additive sanitized-for-TTS channel. Voice consumers
                        # subscribe to TTSTokenEvent; chat consumers ignore it.
                        # If sanitization drops everything (pure markup chunk),
                        # we emit nothing for that chunk — TTS never sees noise.
                        sanitized_chunk = sanitize_for_tts(chunk.delta, preserve_outer_whitespace=True)
                        if sanitized_chunk.strip():
                            yield TTSTokenEvent(text=sanitized_chunk)
                    if chunk.tool_calls_delta:
                        _accumulate_tool_calls(round_tool_calls, chunk.tool_calls_delta)
                    if chunk.usage:
                        final_usage = chunk.usage
                    if chunk.finish_reason is not None:
                        round_finish_reason = chunk.finish_reason
            except LlamaServerTimeout as e:
                if not first_chunk_seen and tool_rounds == 0:
                    raise  # setup error on first round → route returns 504 JSON
                yield ErrorEvent(code="chat_timeout", message=str(e))
                return
            except LlamaServerError as e:
                if not first_chunk_seen and tool_rounds == 0:
                    raise  # setup error on first round → route returns 502 JSON
                yield ErrorEvent(code="chat_server_error", message=str(e))
                return
            except Exception as e:
                if not first_chunk_seen and tool_rounds == 0:
                    raise
                yield ErrorEvent(code="internal_error", message=f"{type(e).__name__}: {e}")
                return

            # ── Round ended. Determine success.
            if round_finish_reason is None:
                yield ErrorEvent(
                    code="incomplete_stream",
                    message="stream closed without finish_reason — no assistant turn saved",
                )
                return

            round_content = "".join(round_content_parts)
            round_tc_tuple = tuple(round_tool_calls) if round_tool_calls else None

            # If the model wants tools and we're within the round budget, dispatch.
            if round_tc_tuple and self.tool_registry is not None:
                if tool_rounds >= self.max_tool_rounds:
                    # Cap hit: keep whatever content we have for this round, mark
                    # the finish reason for the caller, and break out to save+done.
                    final_content_parts.append(round_content)
                    final_finish_reason = "tool_round_limit"
                    break

                # Carry the assistant-with-tool_calls message into the next round's
                # context so the model has a coherent transcript.
                messages = messages + (ChatMessage(
                    role="assistant",
                    content=round_content,
                    tool_calls=list(round_tc_tuple),
                ),)

                # Invoke each tool, emit visibility events, append result messages.
                for tool_call in round_tc_tuple:
                    function = tool_call.get("function") or {}
                    yield ToolCallEvent(
                        call_id=str(tool_call.get("id") or ""),
                        name=str(function.get("name") or ""),
                        args=str(function.get("arguments") or ""),
                    )
                    result_message = self._tool_result_message(tool_call)
                    yield ToolResultEvent(
                        call_id=str(tool_call.get("id") or ""),
                        name=str(function.get("name") or ""),
                        content=result_message.content,
                    )
                    messages = messages + (result_message,)

                tool_rounds += 1
                # Re-enter the round loop for the model's next response.
                continue

            # Tool calls present but no registry to dispatch them — surface
            # the tool_calls in DoneEvent so an external caller (test harness,
            # or a future client that handles dispatch itself) can act on them.
            # This is the "platform plumbing, no in-loop dispatch" contract.
            if round_tc_tuple:
                # Don't save: no content to persist, and the empty-turn
                # poisoning concern is specifically about saving an empty row.
                # Tool-only turns aren't persisted in the conversations table
                # by design (tool_calls are ephemeral plumbing).
                yield DoneEvent(
                    content=round_content,
                    finish_reason=round_finish_reason,
                    tool_calls=round_tc_tuple,
                    usage=final_usage,
                    context_usage=(
                        self._build_context_usage(final_usage, elided_turns)
                        if self.history_token_budget is not None else None
                    ),
                )
                return

            # No tool calls: this round produced the final answer.
            final_content_parts.append(round_content)
            final_finish_reason = round_finish_reason
            break

        accumulated_content = "".join(final_content_parts)

        # An assistant turn with no visible content AND no tool_calls is a generation
        # failure (typically finish_reason=length burned on hidden reasoning). Saving
        # the empty row poisons future loads — on the next user turn the model sees
        # "prior assistant emitted nothing for this prompt" and degenerates, often
        # closing </think> early and verbalising its scratch into content. Reported
        # 2026-06-01: session b94a6200 retry produced 5781 chars of unfenced scratch
        # after an earlier empty turn from the no-cap streaming bug.
        # Mirror of the sync-path guards: surface tool_round_limit + empty as
        # its own loud error so the caller can distinguish "model said nothing"
        # from "model ran out of tool budget mid-research." See sync-path
        # comment for the 2026-06-04 evening probe context.
        if not accumulated_content:
            if final_finish_reason == "tool_round_limit":
                yield ErrorEvent(
                    code="tool_round_limit",
                    message=(
                        f"model exhausted the {self.max_tool_rounds}-round tool "
                        f"budget without emitting visible content. Reduce task "
                        f"scope or raise max_tool_rounds. No assistant turn saved."
                    ),
                )
            else:
                yield ErrorEvent(
                    code="empty_generation",
                    message=f"model produced no visible content (finish_reason={final_finish_reason}); no assistant turn saved",
                )
            return

        self.conv_store.save_turn(
            session_id, self.agent_name, "assistant", accumulated_content,
            finish_reason=final_finish_reason or "stop",
        )

        yield DoneEvent(
            content=accumulated_content,
            finish_reason=final_finish_reason or "stop",
            tool_calls=None,
            usage=final_usage,
            context_usage=(
                self._build_context_usage(final_usage, elided_turns)
                if self.history_token_budget is not None else None
            ),
        )


def _identity_spine_nodes(store: LatticeStore | None, *, agent: str) -> tuple[Node, ...]:
    if store is None:
        return ()
    nodes = []
    for node in store.iter_nodes(agent=agent, include_library=False):
        provenance = node.provenance or {}
        if node.type == "identity" and provenance.get("source") == "legacy_identity_review":
            nodes.append(node)
    return tuple(nodes)
