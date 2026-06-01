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
from soveryn.platform.tools.registry import ToolArgError, ToolRegistry


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


@dataclass(frozen=True)
class ErrorEvent:
    """Stream failed. NO assistant turn was saved when this event fires."""
    code: str
    message: str


# Union type alias for typing
AgentStreamEvent = TokenEvent | DoneEvent | ErrorEvent


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

    def process_message(self, session_id: str, user_message: str) -> ChatResponse:
        """Run one turn. Returns the raw ChatResponse.

        Raises:
          AgentLoopError — session does not exist OR session.agent != self.agent_name
                           (in both cases, NO user turn is saved, NO chat dispatched)
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

        # 1. Save user turn (constraint 6: stays saved if chat later fails).
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
        if self.pinned_text:
            prelude = prelude + (ChatMessage(role="system", content=self.pinned_text),)
        if self.soul_text:
            prelude = prelude + (ChatMessage(role="system", content=self.soul_text),)
        if recall_context:
            prelude = prelude + (ChatMessage(role="system", content=recall_context),)
        messages: tuple[ChatMessage, ...] = prelude + history_messages

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
        #    Any DB error here propagates (constraint 5) — we don't pretend success.
        #    Mirror of the streaming guard: refuse to persist an empty turn with
        #    no tool_calls — that row poisons next-load context (see streaming path).
        if not response.content and not response.tool_calls:
            raise AgentLoopError(
                f"empty_generation: model produced no visible content "
                f"(finish_reason={response.finish_reason}); no assistant turn saved"
            )
        self.conv_store.save_turn(
            session_id, self.agent_name, "assistant", response.content
        )

        # 6. Return raw ChatResponse (constraint 3).
        return response

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
    ) -> "Iterator[AgentStreamEvent]":
        """Streaming variant. Yields TokenEvent per content delta, then either
        DoneEvent (success) or ErrorEvent (mid-stream failure). Assistant turn
        saved ONLY on DoneEvent, AND only if upstream sent an explicit
        finish_reason (constraint 5).

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

        # ── Save user turn FIRST (honest state if stream fails later)
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
        if self.pinned_text:
            prelude = prelude + (ChatMessage(role="system", content=self.pinned_text),)
        if self.soul_text:
            prelude = prelude + (ChatMessage(role="system", content=self.soul_text),)
        if recall_context:
            prelude = prelude + (ChatMessage(role="system", content=recall_context),)
        messages = prelude + history_messages

        request = ChatRequest(
            messages=messages,
            model=self.server.model_alias,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            thinking_budget_tokens=self.thinking_budget_tokens,
        )

        # ── Open the stream. PRE-stream errors propagate (route → JSON 5xx).
        chunk_iter = self.stream_fn(request, self.server, timeout=self.chat_timeout_seconds)

        accumulated_content_parts: list[str] = []
        accumulated_tool_calls: list[dict] = []
        final_finish_reason: str | None = None
        final_usage: dict | None = None
        first_chunk_seen = False

        try:
            for chunk in chunk_iter:
                first_chunk_seen = True
                if chunk.delta:
                    accumulated_content_parts.append(chunk.delta)
                    yield TokenEvent(delta=chunk.delta)
                if chunk.tool_calls_delta:
                    _accumulate_tool_calls(accumulated_tool_calls, chunk.tool_calls_delta)
                if chunk.usage:
                    final_usage = chunk.usage
                if chunk.finish_reason is not None:
                    final_finish_reason = chunk.finish_reason
        except LlamaServerTimeout as e:
            if not first_chunk_seen:
                raise  # setup error → route returns 504 JSON
            yield ErrorEvent(code="chat_timeout", message=str(e))
            return
        except LlamaServerError as e:
            if not first_chunk_seen:
                raise  # setup error → route returns 502 JSON
            yield ErrorEvent(code="chat_server_error", message=str(e))
            return
        except Exception as e:
            # Mid-stream unknown failure: yield error, don't save.
            if not first_chunk_seen:
                raise
            yield ErrorEvent(code="internal_error", message=f"{type(e).__name__}: {e}")
            return

        # ── Stream ended. Determine success: did we see an explicit finish_reason?
        if final_finish_reason is None:
            # No explicit done from upstream — treat as incomplete; do NOT save.
            yield ErrorEvent(
                code="incomplete_stream",
                message="stream closed without finish_reason — no assistant turn saved",
            )
            return

        accumulated_content = "".join(accumulated_content_parts)
        accumulated_tc_tuple = tuple(accumulated_tool_calls) if accumulated_tool_calls else None

        # An assistant turn with no visible content AND no tool_calls is a generation
        # failure (typically finish_reason=length burned on hidden reasoning). Saving
        # the empty row poisons future loads — on the next user turn the model sees
        # "prior assistant emitted nothing for this prompt" and degenerates, often
        # closing </think> early and verbalising its scratch into content. Reported
        # 2026-06-01: session b94a6200 retry produced 5781 chars of unfenced scratch
        # after an earlier empty turn from the no-cap streaming bug.
        if not accumulated_content and not accumulated_tc_tuple:
            yield ErrorEvent(
                code="empty_generation",
                message=f"model produced no visible content (finish_reason={final_finish_reason}); no assistant turn saved",
            )
            return

        self.conv_store.save_turn(session_id, self.agent_name, "assistant", accumulated_content)

        yield DoneEvent(
            content=accumulated_content,
            finish_reason=final_finish_reason,
            tool_calls=accumulated_tc_tuple,
            usage=final_usage,
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
