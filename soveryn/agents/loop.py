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
from typing import Callable

from soveryn.agents.personas import get_persona
from soveryn.agents.recall import format_recall_context
from soveryn.inference.llama_server_client import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    chat as _default_chat,
)
from soveryn.inference.routing import route_for_agent
from soveryn.memory.conversation_store import ConversationStore
from soveryn.memory.lattice import LatticeStore, embed_text as _default_embed


ChatFn = Callable[..., ChatResponse]
EmbedFn = Callable[[str], tuple[float, ...]]


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
        chat_timeout_seconds: float = 60.0,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        system_prompt: str | None = None,
        lattice_store: LatticeStore | None = None,
        recall_k: int = 0,
        recall_threshold: float = 0.70,
        embed_fn: EmbedFn = _default_embed,
    ) -> None:
        self.agent_name = agent_name.lower().strip()
        # Route at construction — RoutingError on unknown/retired names
        # bubbles up here, NEVER at turn-processing time.
        self.server = route_for_agent(self.agent_name)
        self.conv_store = conv_store
        self.chat_fn = chat_fn
        self.chat_timeout_seconds = chat_timeout_seconds
        self.temperature = temperature
        self.max_tokens = max_tokens
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
        self.recall_k = recall_k
        self.recall_threshold = recall_threshold
        self.embed_fn = embed_fn

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
            recall_context = format_recall_context(ranked, threshold=self.recall_threshold)

        # 3. Build immutable tuple[ChatMessage, ...] (constraint 7).
        # System message is prepended at request build time — NOT persisted
        # to conversations table. Empty system_prompt means skip it entirely.
        history_messages = tuple(
            ChatMessage(role=t.role, content=t.content) for t in history_turns
        )
        prelude: tuple[ChatMessage, ...] = ()
        if self.system_prompt:
            prelude = prelude + (ChatMessage(role="system", content=self.system_prompt),)
        if recall_context:
            prelude = prelude + (ChatMessage(role="system", content=recall_context),)
        messages: tuple[ChatMessage, ...] = prelude + history_messages

        # 4. Dispatch chat. Any failure propagates; user turn is already saved.
        request = ChatRequest(
            messages=messages,
            model=self.server.name,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        response = self.chat_fn(request, self.server, timeout=self.chat_timeout_seconds)

        # 5. Save assistant turn from response.content ONLY (constraint 4).
        #    Any DB error here propagates (constraint 5) — we don't pretend success.
        self.conv_store.save_turn(
            session_id, self.agent_name, "assistant", response.content
        )

        # 6. Return raw ChatResponse (constraint 3).
        return response
