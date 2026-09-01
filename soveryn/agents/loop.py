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
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator

from soveryn.agents.personas import get_persona
from soveryn.agents.aetheria.speech_assembler import assemble_ranked_recall
from soveryn.agents.skills import get_skill_index
from soveryn.agents.souls import get_soul
from soveryn.agents.turn_scope import is_trivial_user_turn


def dump_tool_result(result: object) -> str:
    """Serialize a tool result for the model. Bytes in the payload used to
    raise TypeError and kill the whole Kernel commission (OpenCode/GLM
    session blobs, binary stdout). Decode instead of crashing the turn.
    """

    def _default(o: object) -> str:
        if isinstance(o, (bytes, bytearray)):
            return bytes(o).decode("utf-8", "replace")
        return str(o)

    return json.dumps(result, sort_keys=True, default=_default)
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
from soveryn.platform.black_box import BlackBox
from soveryn.platform.continuity.config import ContinuityConfig
from soveryn.platform.steering_rack import SteeringRack
from soveryn.platform.vision_types import VISION_CAPABLE_AGENTS
from soveryn.platform.tools.registry import ToolArgError, ToolRegistry
from soveryn.platform.verification.gate import GateDecision, VerificationGate
from soveryn.platform.voice.sanitize import sanitize_for_tts

try:
    from soveryn.platform.approval.store import ApprovalBroker
except ImportError:  # pragma: no cover
    ApprovalBroker = None  # type: ignore[assignment]


ChatFn = Callable[..., ChatResponse]
EmbedFn = Callable[[str], tuple[float, ...]]
StreamFn = Callable[..., Iterator[StreamChunk]]

# Bounded retry for the narrow, known-intermittent failure where the server
# rejects the MODEL's own malformed tool-call JSON (HTTP 500 "Failed to parse
# tool call arguments"). With temperature > 0 a resend almost always yields
# valid JSON. Observed 2026-06-17: Qwen3.6 on the shared vett-scotty server
# occasionally truncates tool-call args under heavy read_file use.
_TOOLCALL_PARSE_MAX_ATTEMPTS = 3

# Injected when the tool-round budget is spent so the model must answer from
# results already in context instead of requesting more tools (and leaving the
# user with tool_round_limit + empty content). Lightning / tool-eager MoEs hit
# this often on greetings and light research (2026-08-14).
_TOOL_CAP_SYNTH_NOTE = (
    "Tool-call budget for this turn is exhausted. Do NOT call any tools. "
    "Answer the user NOW using only the tool results already in this conversation. "
    "If this was a greeting, chit-chat, or the tools added nothing useful, reply "
    "naturally and briefly. This is your final message for this turn — emit "
    "visible content only, no tool calls."
)


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
class ApprovalPendingEvent:
    """Egress tool is held at the Approval Gate. Emitted after the pending
    request is created and *before* wait(), so /chat_stream can show Allow/Deny
    while the loop blocks for a human decision (or TTL expiry).
    """
    approval_id: str
    citizen: str
    tool: str
    args: dict
    call_id: str


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
    | ApprovalPendingEvent | TTSTokenEvent
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


# Room reserved below context_window for the model's response + estimator
# slack when fitting the tool loop. The history budgeter handles prior turns;
# this handles the CURRENT turn's tool-result accumulation, which it can't.
_CONTEXT_SAFETY_MARGIN_TOKENS = 2048


def _fit_tool_loop_messages(
    messages: tuple[ChatMessage, ...], budget: int
) -> tuple[ChatMessage, ...]:
    """Bound in-turn tool-result accumulation so the prompt fits `budget`.

    Each tool round appends an assistant(tool_calls) message + its tool
    results. A research dive that reads many files in one turn can blow the
    context window (HTTP 400 exceed_context_size) — the history budgeter only
    trims PRIOR turns, never the current turn's growing tool results.

    Strategy (pairing-safe): preserve the prelude through the last user turn,
    then drop the OLDEST complete tool-round groups (assistant-with-tool_calls
    + its paired tool messages) until the estimate fits. If a single remaining
    round still exceeds budget, size that round's tool-result contents down to
    fit. Never orphans a tool result from its assistant tool_call.
    """
    est = lambda ms: sum(_estimate_message_tokens(m) for m in ms)
    if est(messages) <= budget:
        return messages
    msgs = list(messages)
    user_idxs = [i for i, m in enumerate(msgs) if m.role == "user"]
    if not user_idxs:
        return messages  # no anchor to preserve; leave it (server will reject)
    cut = user_idxs[-1] + 1
    head, tail = msgs[:cut], msgs[cut:]
    groups: list[list[ChatMessage]] = []
    for m in tail:
        if m.role == "assistant" and m.tool_calls:
            groups.append([m])
        elif groups:
            groups[-1].append(m)
        else:
            groups.append([m])  # defensive: orphan tail (shouldn't happen)
    flat = lambda gs: [x for g in gs for x in g]
    while len(groups) > 1 and est(head + flat(groups)) > budget:
        groups.pop(0)
    if est(head + flat(groups)) <= budget:
        return tuple(head + flat(groups))
    # One round alone still exceeds budget: size its tool results down to fit.
    last = groups[-1]
    nonresult = [m for m in last if m.role != "tool"]
    results = [m for m in last if m.role == "tool"]
    note = "\n[…tool result truncated to fit context…]"
    note_tokens = _estimate_tokens(note)
    avail = budget - est(head) - est(nonresult)
    per = max(8, avail // max(1, len(results)))
    sized: list[ChatMessage] = []
    for m in results:
        if isinstance(m.content, str) and _estimate_message_tokens(m) > per:
            # leave room within `per` for the per-message overhead + the note
            keep = max(0, (per - _PER_MESSAGE_OVERHEAD_TOKENS - note_tokens) * 4)
            sized.append(ChatMessage(
                role="tool",
                content=m.content[:keep] + note,
                tool_call_id=m.tool_call_id,
                tool_calls=m.tool_calls,
            ))
        else:
            sized.append(m)
    return tuple(head + nonresult + sized)


# Memory Grades PR5 (2026-08-11): history budget is HISTORY-ONLY by default.
# Prelude (soul / pinned / continuity / spine / recall) is not charged against
# history_token_budget — charging it starved chat history under a fat Aetheria
# prelude. Soft budgets on prelude/total are reported via context_usage only.
PRELUDE_SOFT_BUDGET_TOKENS = 3500
TOTAL_INPUT_SOFT_BUDGET_TOKENS = 12_000


def _apply_history_budget(
    prelude: tuple[ChatMessage, ...],
    history: tuple[ChatMessage, ...],
    budget: int,
    *,
    charge_prelude: bool = False,
) -> tuple[tuple[ChatMessage, ...], ChatMessage | None, int]:
    """Drop oldest history turns until the charged set fits inside budget.

    Always preserves history[-1] (the just-saved user message). Returns:
      (possibly_trimmed_history, elision_marker_or_None, elided_count)

    Default charge_prelude=False (Memory Grades PR5, fleet-wide): only history
    tokens count against budget. Prelude still rides the wire; it is governed
    by context_window fit (_fit_tool_loop_messages) and soft budgets in
    context_usage, not by this trimmer.

    charge_prelude=True restores the pre-PR5 behavior (prelude + history share
    one envelope) for callers that explicitly need it.

    If the most recent turn alone (and charged prelude, when enabled) already
    blows the budget, we keep the newest turn, drop older history when
    possible, and surface pressure via context_usage.
    """
    if not history:
        return history, None, 0
    prelude_tokens = sum(_estimate_message_tokens(m) for m in prelude)
    history_tokens = [_estimate_message_tokens(m) for m in history]
    history_sum = sum(history_tokens)
    charged = (prelude_tokens + history_sum) if charge_prelude else history_sum
    if charged <= budget:
        return history, None, 0

    kept = list(history)
    kept_tokens = list(history_tokens)
    dropped = 0
    # Running charged total as we drop oldest history turns.
    total = charged
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


ContinuityTailFingerprint = tuple[tuple[str, str, int, tuple[tuple[str, str | None], ...]], ...]
# Full continuity fingerprint = the cross-session tails AND the Active Focus
# block. Folding the rendered active-focus string in means a change to the
# coordination boards (new directive, status flip, archive) invalidates the
# cache exactly the same way a new session tail does — the brief never goes
# stale relative to the work actually in flight.
# (tails_fp, active_focus_text, acttruth_act_truth_text)
ContinuityFingerprint = tuple[ContinuityTailFingerprint, str, str]


@dataclass(frozen=True)
class ContinuityCacheEntry:
    fingerprint: ContinuityFingerprint
    text: str


@dataclass(frozen=True)
class RecallCacheEntry:
    text: str
    query_text: str
    expires_at: float
    remaining_reuses: int


@dataclass
class SessionContextCache:
    continuity: dict[str, ContinuityCacheEntry] = field(default_factory=dict)
    recall: dict[str, RecallCacheEntry] = field(default_factory=dict)


_RECALL_CACHE_TTL_SECONDS = 300.0
_RECALL_CACHE_REUSE_TURNS = 12


def _continuity_fingerprint(tails) -> ContinuityTailFingerprint:
    """Fingerprint the underlying cross-session activity, not render time."""
    fp = []
    for tail in tails:
        pairs = tuple((pair.user, pair.assistant) for pair in tail.paired_turns)
        fp.append((tail.session_id, tail.updated_at, len(tail.paired_turns), pairs))
    return tuple(fp)


def _build_observation_entry(tool_call: dict, result_message: ChatMessage) -> dict:
    """Pack one tool result into the BlackBox observation shape.

    `result_message.content` is the JSON-serialised result from
    `_tool_result_message` — when the handler raised, it's `{"error": "...",
    "message": "..."}`. Decoding it lets the recorder count tool errors
    distinctly from successful invocations.
    """
    function = tool_call.get("function") or {}
    name = str(function.get("name") or "")
    content = result_message.content if isinstance(result_message.content, str) else ""
    error: str | None = None
    if content:
        try:
            decoded = json.loads(content)
        except (TypeError, json.JSONDecodeError):
            decoded = None
        if isinstance(decoded, dict) and decoded.get("error"):
            error = str(decoded["error"])
    return {
        "call_id": result_message.tool_call_id or "",
        "name": name,
        "content": content,
        "error": error,
    }


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
        active_context=None,
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
        skills_dir: Path | None = None,
        pinned_text: str = "",
        continuity_config: ContinuityConfig | None = None,
        coord_store: "CoordinationStore | None" = None,
        black_box: BlackBox | None = None,
        steering_rack: SteeringRack | None = None,
        verification_gate: "VerificationGate | None" = None,
        approval_gate: "ApprovalBroker | None" = None,
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
        # Skills are disk-first + hot-reload: the index is re-read from disk
        # every turn (see _build_skills_index) so a freshly-learned skill is
        # visible next turn without a restart. skills_dir=None falls back to
        # the config default inside get_skill_index.
        self.skills_dir = skills_dir

        # Pinned memory is Aetheria's relationship substrate (third identity
        # layer between persona and soul). Default empty = skip — Vett and
        # Scotty rely on this. Production opts Aetheria in via startup.py.
        self.pinned_text: str = pinned_text

        # Cross-Surface Continuity (Aetheria-only). None = disabled; the
        # helper short-circuits to "" so non-aetheria loops never pay any
        # query cost.
        self.continuity_config = continuity_config
        # Coordination store for the Active Focus block (Aetheria-only, derived
        # on-read in _build_continuity_brief). None = no active-focus context.
        self.coord_store = coord_store
        self.black_box = black_box
        self.steering_rack = steering_rack
        # Deterministic verification gate (Vett-only in v1). None → no gate;
        # the gate itself is owner-scoped so even when wired to every loop it
        # is a no-op for non-owner agents. `_gate_active` is the single guard
        # the finalization paths consult before running any gate logic, so a
        # non-owner turn finalizes on the exact pre-gate code path.
        self.verification_gate = verification_gate
        self._gate_active = (
            verification_gate is not None
            and verification_gate.applies_to(self.agent_name)
        )
        # Deterministic approval gate (egress boundary). None → no gate; every
        # egress tool call passes through unimpeded. When wired, the gate
        # intercepts `optional_egress` tools at the tool-dispatch boundary,
        # blocks until a human approves, and denies on timeout (fail-safe).
        self.approval_gate = approval_gate
        # Cross-rail live thread (ActiveContextService | None). Optional so
        # every existing construction site and test keeps working unchanged.
        self.active_context = active_context
        self.session_context_cache = SessionContextCache()

    def _rail_for(self, session_id: str) -> str:
        """Map a session to the rail it represents, from its title prefix."""
        try:
            session = self.conv_store.get_session(session_id)
        except Exception:
            return "chat"
        title = (getattr(session, "title", "") or "") if session else ""
        for prefix, rail in (
            ("[heartbeat]", "heartbeat"), ("[voice]", "voice"),
            ("[signal]", "signal"), ("[m]", "messenger"),
            ("[dream]", "dream"), ("[patrol]", "patrol"),
            ("[webhook]", "webhook"), ("[presence]", "presence"),
        ):
            if title.startswith(prefix):
                return rail
        return "chat"

    def _record_active_exchange(self, session_id: str, user_message: str,
                                assistant_text: str) -> None:
        """Write the live thread. Never allowed to break a turn.

        Called from BOTH process_message and process_message_stream — a write
        in only one is bypassed by whichever surface uses the other, the same
        trap the staged-X-post pre-turn hook documents in routes/chat.py.
        """
        if self.active_context is None:
            return
        try:
            self.active_context.record_exchange(
                rail=self._rail_for(session_id),
                user_text=user_message,
                assistant_text=assistant_text,
            )
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                "active context write failed; turn unaffected"
            )

    def _render_active_context(self) -> str:
        """Render the cross-rail live thread, or "" when unwired.

        Deliberately NOT part of the continuity cache fingerprint: the whole
        point is that it reflects what another rail did seconds ago, so a cache
        keyed to this session's tails would serve a stale thread.
        """
        if self.active_context is None:
            return ""
        try:
            return self.active_context.render()
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                "active context render failed; serving without it"
            )
            return ""

    def _acttruth_act_truth_brief(self) -> str:
        """Episodic act-truth + soft lessons for this agent (ActTruth by SOVERYN).

        Crew-wide: each agent sees quiet failures and recent tool outcomes —
        not vibe memory. Repeat FAILs become LESSONS so they stop blind loops.
        Best-effort; never raises.
        """
        try:
            from soveryn.platform.acttruth.hooks import get_acttruth
            from soveryn.platform.acttruth.lessons import lessons_brief

            truth = get_acttruth().ledger.recall_brief(
                self.agent_name, limit=6, window_hours=24.0, max_chars=900,
            )
            lessons = lessons_brief(self.agent_name)
            if truth and lessons:
                return f"{truth}\n\n{lessons}"
            return truth or lessons
        except Exception:
            return ""

    def _with_acttruth_brief(self, text: str) -> str:
        block = self._acttruth_act_truth_brief()
        if not block:
            return text
        return f"{text}\n\n{block}" if text else block

    def _build_continuity_brief(self, session_id: str) -> str:
        """Build or reuse the Cross-Surface Recent Activity Brief.

        Cache invalidation is keyed to the underlying cross-session activity,
        not the clock. Relative-time strings are rendered once and stay stable
        until a different session tail appears.

        Continuum act-truth is folded in for every agent (including when
        cross-surface continuity is disabled) so quiet failures stay visible.
        """
        if self.continuity_config is None or not self.continuity_config.enabled:
            return self._with_acttruth_brief("")
        # Cross-session tails (multi-rail conversation continuity) stay
        # Aetheria-only. Active Focus (board awareness) also goes to any agent
        # wired with a coord_store — Vett, so she can see what's in flight and
        # whether her own messages up to the hub were received.
        is_aetheria = self.agent_name == "aetheria"
        if not is_aetheria and self.coord_store is None:
            # A peer with no coord_store still gets its own live thread —
            # otherwise "the whole team is whole" is false for exactly the
            # agent with the fewest other continuity sources (Scotty).
            return self._with_acttruth_brief(self._render_active_context())
        try:
            session = self.conv_store.get_session(session_id)
            # Autonomous sessions ([heartbeat], [dream], [patrol]) are excluded
            # from cross-session TAILS on purpose — 26 wakes a day of transcript
            # would bury the budget. Before 2026-07-28 they returned "" here and
            # so received no continuity at all, which is why her most
            # independent thinking never reached another rail and never came
            # back to her. They now get the ACTIVE CONTEXT block: state, not
            # transcript, and small enough to always afford.
            autonomous = (
                session is not None
                and self.continuity_config.session_is_autonomous(session.title)
            )
            if autonomous:
                return self._with_acttruth_brief(self._render_active_context())
            tails = ()
            if is_aetheria:
                from soveryn.platform.continuity.store import recent_cross_session_tails
                tails = recent_cross_session_tails(
                    self.conv_store,
                    agent=self.agent_name,
                    current_session_id=session_id,
                    config=self.continuity_config,
                )
            # Active Focus — the work currently in flight across the coordination
            # boards, derived on-read (no LLM, no separate cache; the render is
            # as fresh as the boards). Folded into the same system message as
            # the recent-activity brief so the continuity context arrives as one
            # block. Bare data, never instruction.
            active_focus = ""
            if self.coord_store is not None:
                from soveryn.platform.continuity.active_focus import (
                    derive_dispatch_states,
                    render_active_focus,
                )
                # Communication truth per node, from THIS agent's perspective:
                #   Aetheria → her outbound directives (sent to vett, awaiting/
                #     replied), read from the [direct:] sessions.
                #   a peer → her messages up to the hub (sent to aetheria,
                #     received), read from the coord_event_log ledger.
                # So an owned Open node reads as actually-dispatched instead of
                # being mistaken for never-handed-off (the 2026-06-19 gap).
                if is_aetheria:
                    dispatch_states = derive_dispatch_states(self.conv_store)
                else:
                    dispatch_states = self.coord_store.delivery_states_for_actor(
                        self.agent_name
                    )
                active_focus = render_active_focus(
                    self.coord_store.list_nodes(),
                    dispatch_states=dispatch_states,
                    self_agent=self.agent_name,
                )
            acttruth_block = self._acttruth_act_truth_brief()
            fingerprint: ContinuityFingerprint = (
                _continuity_fingerprint(tails),
                active_focus,
                acttruth_block,
            )
            cached = self.session_context_cache.continuity.get(session_id)
            if cached is not None and cached.fingerprint == fingerprint:
                return cached.text
            text = ""
            if tails:
                from soveryn.platform.continuity.brief import build_recent_activity_brief
                text = build_recent_activity_brief(tails, config=self.continuity_config)
            if active_focus:
                text = f"{text}\n\n{active_focus}" if text else active_focus
            active_context = self._render_active_context()
            if active_context:
                text = f"{text}\n\n{active_context}" if text else active_context
            if acttruth_block:
                text = f"{text}\n\n{acttruth_block}" if text else acttruth_block
            self.session_context_cache.continuity[session_id] = ContinuityCacheEntry(
                fingerprint=fingerprint,
                text=text,
            )
            return text
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                "continuity brief build failed; serving without it"
            )
            return self._with_acttruth_brief("")

    def _build_recall_context(self, session_id: str, user_message: str) -> str:
        """Build or reuse live recall across a coherent local thread."""
        if self.recall_k <= 0:
            return ""
        now = time.monotonic()
        cached = self.session_context_cache.recall.get(session_id)
        if (
            cached is not None
            and cached.remaining_reuses > 0
            and now < cached.expires_at
        ):
            self.session_context_cache.recall[session_id] = RecallCacheEntry(
                text=cached.text,
                query_text=cached.query_text,
                expires_at=cached.expires_at,
                remaining_reuses=cached.remaining_reuses - 1,
            )
            return cached.text

        # Librarian asymmetric prefix: recall queries embed as "query", memories
        # as "document". embed_fn is normally embed_text (accepts prompt); test
        # fakes may not, so fall back.
        try:
            query_vector = self.embed_fn(user_message, prompt="query")
        except TypeError:
            query_vector = self.embed_fn(user_message)
        ranked = self.lattice_store.find_nodes_by_embedding(
            self.agent_name,
            query_vector,
            limit=self.recall_k,
            threshold=self.recall_threshold,
        )
        facts: tuple = ()
        impl = getattr(type(self.lattice_store), "find_canonical_facts", None)
        if callable(impl) and getattr(impl, "__name__", "") == "find_canonical_facts":
            try:
                facts = impl(self.lattice_store, self.agent_name, user_message, limit=3) or ()
            except Exception:
                logging.getLogger(__name__).exception(
                    "canonical fact rail failed; serving cosine recall only"
                )
                facts = ()
        text = assemble_ranked_recall(ranked, fact_nodes=facts)
        self.session_context_cache.recall[session_id] = RecallCacheEntry(
            text=text,
            query_text=user_message,
            expires_at=now + _RECALL_CACHE_TTL_SECONDS,
            remaining_reuses=_RECALL_CACHE_REUSE_TURNS,
        )
        return text

    def _build_temporal_context(self, now: datetime | None = None) -> str:
        """Ambient temporal data prepended to the current user turn.

        Without this, agents confabulate time-of-day from session pacing
        (long thread → "it's late," etc.). Injecting an explicit timestamp
        per turn gives the model ground truth — she SEES the time, so she
        has no reason to invent it.

        Tone: bare data, no instruction. An earlier version of this string
        carried a directive — "Time of day matters — anchor your sense of
        'now' against this..." — which made Aetheria narrate the clock in
        every reply ("anchored. Saturday night, 22:49"). Compliance pattern:
        when prompted to demonstrate something, models demonstrate by saying
        the thing back. The fix is to give her the data without telling her
        what to do with it. See [[feedback-ambient-context-not-instruction]].

        Per-turn freshness by design — no caching. Spliced onto the current
        user message at request-build time (NOT into the prelude), so the
        prelude (persona / pinned / soul / identity / recall) stays byte-
        identical across turns and the KV-cache prefix remains reusable.
        Mirrors the vision-splice pattern: DB save is text-only, the wire-
        level user message gets the temporal prefix.

        Part-of-day buckets (24h local time):
            05:00 – 11:59  morning
            12:00 – 16:59  afternoon
            17:00 – 20:59  evening
            21:00 – 04:59  night
        """
        if now is None:
            now = datetime.now().astimezone()
        iso = now.isoformat(timespec="seconds")
        day_of_week = now.strftime("%A")
        hour = now.hour
        if 5 <= hour < 12:
            part = "morning"
        elif 12 <= hour < 17:
            part = "afternoon"
        elif 17 <= hour < 21:
            part = "evening"
        else:
            part = "night"
        return f"[Now: {iso} ({day_of_week} {part})]"

    def _build_identity_context(self) -> str:
        """Identity spine is stable prelude context, independent of the user turn."""
        return assemble_ranked_recall(
            (),
            identity_nodes=_identity_spine_nodes(self.identity_spine_store, agent=self.agent_name),
        )

    def _build_skills_index(self) -> str:
        """Skills index is disk-first, re-read every turn (hot-reload).

        Tiny (one line per skill) so the per-turn read is negligible. A
        skill learned mid-session appears next turn with no restart. Empty
        (no skills on disk yet) → "" so the prelude block is skipped entirely.
        Labeled for the model; soft-capped so a fat index cannot bloat prelude.
        """
        raw = get_skill_index(self.agent_name, skills_dir=self.skills_dir).strip()
        if not raw:
            return ""
        # ~2k tokens soft budget for the index (design: citizen skill capture).
        max_chars = 8000
        if len(raw) > max_chars:
            raw = raw[: max_chars - 1].rstrip() + "…"
        return (
            "[PROCEDURAL SKILLS — house craft for this citizen]\n"
            "Index only. Call recall_skill with a name below to load the full how-to.\n"
            f"{raw}\n"
            "[/PROCEDURAL SKILLS]"
        )

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

    def _tools_for_user_turn(self, user_message: str) -> tuple[dict, ...] | None:
        """Tool schemas for this turn, or None when the turn should be tool-free.

        Trivial social/ack messages (hey/ok/thanks) get no tools — Lightning
        otherwise inventories the whole house on a greeting (2026-08-14).
        """
        if is_trivial_user_turn(user_message):
            return None
        return self._tool_schemas() or None

    def _messages_for_tool_cap_synthesis(
        self, messages: tuple[ChatMessage, ...]
    ) -> tuple[ChatMessage, ...]:
        """Append the force-final note and re-fit under the history budget."""
        return self._fit(messages + (
            ChatMessage(role="system", content=_TOOL_CAP_SYNTH_NOTE),
        ))

    @staticmethod
    def _as_tool_cap_final(response: ChatResponse) -> ChatResponse:
        """Normalize a force-final generation: drop tool_calls, mark the cap.

        Content (if any) is preserved so the user still gets an answer after
        the model burned the tool budget. Empty content stays empty so the
        existing loud tool_round_limit / empty_generation guards fire.
        """
        return ChatResponse(
            content=response.content or "",
            finish_reason="tool_round_limit",
            tool_calls=None,
            usage=response.usage,
            raw=response.raw,
        )

    def _synthesize_after_tool_cap(
        self, messages: tuple[ChatMessage, ...]
    ) -> ChatResponse:
        """One no-tools generation after the tool budget is spent.

        Used as a safety net when the model still requested tools at the cap
        (or returned empty after the forced last round). Never re-offers tools.
        """
        request = ChatRequest(
            messages=self._messages_for_tool_cap_synthesis(messages),
            model=self.server.model_alias,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            tools=None,
            tool_choice=None,
            thinking_budget_tokens=self.thinking_budget_tokens,
        )
        return self._as_tool_cap_final(self._chat(request))

    def _chat(self, request: ChatRequest) -> ChatResponse:
        """Invoke the model, retrying ONLY the narrow, known-intermittent
        failure where the server rejects the model's own malformed tool-call
        JSON (HTTP 500 'Failed to parse tool call arguments'). With temperature
        > 0 a resend almost always yields valid JSON. Every other error — real
        4xx/5xx, timeouts — propagates immediately, unretried. One bad tool
        call from the model shouldn't surface as a user-facing error."""
        attempt = 0
        while True:
            try:
                return self.chat_fn(
                    request, self.server, timeout=self.chat_timeout_seconds
                )
            except LlamaServerError as exc:
                attempt += 1
                retryable = exc.status_code == 500 and "parse tool call" in str(exc).lower()
                if retryable and attempt < _TOOLCALL_PARSE_MAX_ATTEMPTS:
                    logging.getLogger(__name__).warning(
                        "%s emitted malformed tool-call JSON (attempt %d/%d); resending",
                        self.server.model_alias, attempt, _TOOLCALL_PARSE_MAX_ATTEMPTS,
                    )
                    continue
                raise

    def _fit(self, messages: tuple[ChatMessage, ...]) -> tuple[ChatMessage, ...]:
        """Trim the message list to fit the server context window before a
        call, bounding the current turn's tool-result accumulation. No-op when
        context_window is unset (tests) or the messages already fit."""
        if self.context_window is None:
            return messages
        budget = max(1, self.context_window - self.max_tokens - _CONTEXT_SAFETY_MARGIN_TOKENS)
        return _fit_tool_loop_messages(messages, budget)

    def _gate_decision(
        self,
        *,
        answer_text: str,
        question_text: str,
        tool_ledger: tuple[str, ...],
        budget: int,
    ) -> "GateDecision | None":
        """Consult the verification gate, FAIL-OPEN on any error.

        A detector/gate bug must NEVER crash or hang a turn — on ANY exception
        we log and return None, and the caller emits the answer normally. This
        is the safety contract: a gate bug degrades to the old (pre-gate)
        behavior, it never breaks the fleet. Returns None both when the gate is
        inactive (non-owner agent) and when it errored.
        """
        if not self._gate_active or self.verification_gate is None:
            return None
        try:
            return self.verification_gate.evaluate(
                answer_text=answer_text,
                question_text=question_text,
                tool_ledger=tool_ledger,
                budget=budget,
            )
        except Exception:  # noqa: BLE001 — fail-open is the whole point
            logging.getLogger(__name__).exception(
                "verification gate raised for agent %s; emitting answer as-is "
                "(fail-open)", self.agent_name,
            )
            return None

    def process_message(
        self,
        session_id: str,
        user_message: str,
        attachments: tuple[str, ...] | None = None,
        *,
        source: str = "direct",
        skip_user_save: bool = False,
    ) -> ChatResponse:
        """Run one turn. Returns the raw ChatResponse.

        attachments — when non-empty, the current (last) user message's
        wire-level content is replaced with an OpenAI vision-format list
        ([{"type": "text", ...}, {"type": "image_url", ...}, ...]). The DB
        row still stores `user_message` as plain text (no schema migration;
        multimodal history persistence is intentionally deferred). Only
        agents whose serving profile loads an mmproj projector
        (VISION_CAPABLE_AGENTS) can decode images — passing attachments to
        any other agent raises AgentLoopError BEFORE save_turn so guard
        rejections don't pollute history with a phantom user turn.

        source — tags both the user and assistant turn's `source` column
        (default "direct", i.e. a human chat turn). The heartbeat daemon
        passes source="heartbeat" so pulse turns are distinguishable from
        real human turns in the UI. Threaded straight to save_turn — see
        ConversationStore.save_turn.

        skip_user_save — Messages deferred path already persisted the user
        turn so the composer can unblock. Do not write it twice.

        Raises:
          AgentLoopError — session does not exist OR session.agent != self.agent_name
                           OR attachments passed to a non-vision-capable agent
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
        # phantom user turn behind. Only agents whose serving profile loads an
        # mmproj projector (VISION_CAPABLE_AGENTS) can decode images; routing
        # any other agent's attachments would silently drop the image at the
        # wire boundary.
        if attachments and self.agent_name not in VISION_CAPABLE_AGENTS:
            raise AgentLoopError(
                f"attachments only supported for vision-capable agents "
                f"(agent {self.agent_name!r} has no vision model loaded)"
            )

        # 1. Save user turn (constraint 6: stays saved if chat later fails).
        # Text-only by design — vision parts live in-flight, not in the DB.
        if not skip_user_save:
            self.conv_store.save_turn(
                session_id, self.agent_name, "user", user_message, source=source,
            )

        # 2. Load history (includes the just-saved user turn).
        history_turns = self.conv_store.load_history(session_id)

        continuity_brief = self._build_continuity_brief(session_id)
        recall_context = self._build_recall_context(session_id, user_message)
        identity_context = self._build_identity_context()
        skills_index = self._build_skills_index()

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
        if continuity_brief:
            prelude = prelude + (ChatMessage(role="system", content=continuity_brief),)
        if self.pinned_text:
            prelude = prelude + (ChatMessage(role="system", content=self.pinned_text),)
        if self.soul_text:
            prelude = prelude + (ChatMessage(role="system", content=self.soul_text),)
        if identity_context:
            prelude = prelude + (ChatMessage(role="system", content=identity_context),)
        if recall_context:
            prelude = prelude + (ChatMessage(role="system", content=recall_context),)
        if skills_index:
            prelude = prelude + (ChatMessage(role="system", content=skills_index),)

        elided_turns = 0
        if self.history_token_budget is not None:
            history_messages, marker, elided_turns = _apply_history_budget(
                prelude, history_messages, self.history_token_budget,
                charge_prelude=False,
            )
            if marker is not None:
                prelude = prelude + (marker,)
        messages: tuple[ChatMessage, ...] = prelude + history_messages
        # Snapshot for context_usage (after history trim; elision marker in prelude).
        _usage_prelude = prelude
        _usage_history = history_messages

        # Temporal splice — prepend "[Current temporal context: ...]\n\n" to
        # the current (last) user message's text. Lives on the user turn (NOT
        # the prelude) so the prelude stays byte-identical across turns and
        # the KV-cache prefix remains reusable. DB save above is text-only,
        # mirroring the vision splice pattern below.
        temporal_context = self._build_temporal_context()
        last = messages[-1]
        assert last.role == "user", (
            "last message must be the current user turn for the temporal splice"
        )
        spliced_user_text = f"{temporal_context}\n\n{user_message}"
        messages = messages[:-1] + (
            ChatMessage(role="user", content=spliced_user_text),
        )

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
            current_text = last.content if isinstance(last.content, str) else spliced_user_text
            spliced_content: list[dict] = [{"type": "text", "text": current_text}]
            for url in attachments:
                spliced_content.append({"type": "image_url", "image_url": {"url": url}})
            messages = messages[:-1] + (
                ChatMessage(role="user", content=spliced_content),
            )

        # 4. Dispatch chat. Any failure propagates; user turn is already saved.
        # Black-box recorder — begins now so wall-time covers the full dispatch.
        # No-op when no tools fire (begin_turn returns a recorder that finalizes
        # to nothing if record_action is never called).
        recorder = (
            self.black_box.begin_turn(
                session_id=session_id,
                agent=self.agent_name,
                user_message=user_message,
            )
            if self.black_box is not None else None
        )
        messages = self._fit(messages)
        # Fixed for the whole turn: trivial "hey"/"ok" never see a tool menu.
        turn_tools = self._tools_for_user_turn(user_message)
        request = ChatRequest(
            messages=messages,
            model=self.server.model_alias,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            tools=turn_tools,
            thinking_budget_tokens=self.thinking_budget_tokens,
        )
        response = self._chat(request)

        tool_rounds = 0
        # Verification ledger + budget for the Vett-only finalization gate.
        # turn_tool_ledger accumulates the NAMES of tools invoked this turn so
        # the gate can ask "did any verify tool run?". verify_budget bounds the
        # number of forced-verify rounds (0 when the gate is inactive → the
        # outer loop runs exactly once, identical to the pre-gate path).
        turn_tool_ledger: list[str] = []
        verify_budget = (
            self.verification_gate.forced_verify_budget
            if self._gate_active and self.verification_gate is not None else 0
        )

        # Outer gate-continuation loop. Without an active gate it iterates once.
        while True:
            while response.tool_calls and self.tool_registry is not None:
                if tool_rounds >= self.max_tool_rounds:
                    # Cap hit with the model still asking for tools. Do NOT
                    # dispatch those calls — force one no-tools synthesis from
                    # results already in `messages` so the user gets an answer
                    # instead of tool_round_limit + empty content (Lightning
                    # thrash, 2026-08-14).
                    if tool_rounds > 0 and not (response.content or "").strip():
                        try:
                            response = self._synthesize_after_tool_cap(messages)
                        except Exception:
                            logging.getLogger(__name__).exception(
                                "tool-cap synthesis failed for %s; surfacing limit",
                                self.agent_name,
                            )
                            response = ChatResponse(
                                content=response.content or "",
                                finish_reason="tool_round_limit",
                                tool_calls=response.tool_calls,
                                usage=response.usage,
                                raw=response.raw,
                            )
                    else:
                        response = ChatResponse(
                            content=response.content or "",
                            finish_reason="tool_round_limit",
                            tool_calls=response.tool_calls,
                            usage=response.usage,
                            raw=response.raw,
                        )
                    break
                # Record tool names for the verification ledger BEFORE dispatch.
                for _tc in response.tool_calls:
                    _fn = _tc.get("function") or {}
                    turn_tool_ledger.append(str(_fn.get("name") or ""))
                if recorder is not None:
                    recorder.record_action(
                        round_index=tool_rounds,
                        tool_calls=list(response.tool_calls),
                        content=response.content or "",
                    )
                messages = messages + (ChatMessage(
                    role="assistant",
                    content=response.content,
                    tool_calls=response.tool_calls,
                ),)
                result_messages = [
                    self._tool_result_message(
                        tool_call,
                        session_id=session_id,
                        source=source,
                        attachments=attachments,
                    )
                    for tool_call in response.tool_calls
                ]
                if recorder is not None:
                    recorder.record_observation(
                        round_index=tool_rounds,
                        results=[
                            _build_observation_entry(tc, rm)
                            for tc, rm in zip(response.tool_calls, result_messages)
                        ],
                    )
                messages = messages + tuple(result_messages)
                messages = self._fit(messages)
                # Last allowed tool dispatch → next generation is force-final
                # (no tools). Prevents burning the final slot on another tool
                # chain that leaves content empty.
                force_final = (tool_rounds + 1) >= self.max_tool_rounds
                if force_final:
                    request = ChatRequest(
                        messages=self._messages_for_tool_cap_synthesis(messages),
                        model=self.server.model_alias,
                        temperature=self.temperature,
                        max_tokens=self.max_tokens,
                        tools=None,
                        tool_choice=None,
                        thinking_budget_tokens=self.thinking_budget_tokens,
                    )
                else:
                    request = ChatRequest(
                        messages=messages,
                        model=self.server.model_alias,
                        temperature=self.temperature,
                        max_tokens=self.max_tokens,
                        tools=turn_tools,
                        thinking_budget_tokens=self.thinking_budget_tokens,
                    )
                response = self._chat(request)
                tool_rounds += 1
                if force_final:
                    # No-tools generation already requested; strip any sticky
                    # tool_calls and stop the tool loop.
                    response = self._as_tool_cap_final(response)
                    break

            # ── Verification gate at final-answer finalization (Vett-only,
            # fail-open). Only a GENUINE final answer is gated: a
            # tool_round_limit break is left alone (the round budget is already
            # spent — there is nothing more to force), and a turn with no
            # content falls through to the loud empty/limit guards below.
            if (
                self._gate_active
                and response.content
                and not response.tool_calls
                and response.finish_reason != "tool_round_limit"
            ):
                decision = self._gate_decision(
                    answer_text=response.content,
                    question_text=user_message,
                    tool_ledger=tuple(turn_tool_ledger),
                    budget=verify_budget,
                )
                if (
                    decision is not None
                    and decision.action == "hold"
                    and tool_rounds < self.max_tool_rounds
                ):
                    # HOLD: do not emit. Inject the corrective note and force
                    # tool_choice=required on the next chat so the model cannot
                    # keep narrating "I'll verify…" without a real tool call
                    # (prompt-only holds were still failing 2026-08-14).
                    # Trivial turns keep tools=None (gate also emits for them).
                    verify_budget -= 1
                    messages = messages + (ChatMessage(
                        role="system", content=decision.note,
                    ),)
                    messages = self._fit(messages)
                    schemas = turn_tools
                    request = ChatRequest(
                        messages=messages,
                        model=self.server.model_alias,
                        temperature=self.temperature,
                        max_tokens=self.max_tokens,
                        tools=schemas,
                        tool_choice="required" if schemas else None,
                        thinking_budget_tokens=self.thinking_budget_tokens,
                    )
                    response = self._chat(request)
                    continue
                if decision is not None and decision.action == "floor":
                    # Budget exhausted and still unsourced → honest floor. Never
                    # falls back to the drafted guess.
                    response = ChatResponse(
                        content=decision.answer,
                        finish_reason=response.finish_reason,
                        tool_calls=None,
                        usage=response.usage,
                        raw=response.raw,
                    )
            break

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
            if recorder is not None:
                recorder.finalize(
                    final_content="",
                    finish_reason="tool_round_limit",
                    usage=response.usage,
                )
            raise AgentLoopError(
                f"tool_round_limit: model exhausted the {self.max_tool_rounds}-round "
                f"tool budget without emitting visible content. Reduce task scope or "
                f"raise max_tool_rounds. No assistant turn saved."
            )
        if not response.content and not response.tool_calls:
            if recorder is not None:
                recorder.finalize(
                    final_content="",
                    finish_reason="empty_generation",
                    usage=response.usage,
                )
            raise AgentLoopError(
                f"empty_generation: model produced no visible content "
                f"(finish_reason={response.finish_reason}); no assistant turn saved"
            )
        self.conv_store.save_turn(
            session_id, self.agent_name, "assistant", response.content,
            source=source, finish_reason=response.finish_reason,
        )
        self._record_active_exchange(session_id, user_message, response.content)
        if recorder is not None:
            recorder.finalize(
                final_content=response.content,
                finish_reason=response.finish_reason,
                usage=response.usage,
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
                context_usage=self._build_context_usage(
                    response.usage,
                    elided_turns,
                    prelude=_usage_prelude,
                    history=_usage_history,
                ),
            )
        return response

    def _build_context_usage(
        self,
        usage: dict | None,
        elided_turns: int,
        *,
        prelude: tuple[ChatMessage, ...] | None = None,
        history: tuple[ChatMessage, ...] | None = None,
    ) -> dict:
        """Build the context_usage payload returned alongside a ChatResponse.

        prompt_tokens comes from the model's reported usage when available;
        if the server didn't return usage (e.g. a fake_chat in tests), we
        fall back to 0 so the UI math is defined.

        Memory Grades PR5: budget_tokens is HISTORY-ONLY. prelude_tokens /
        history_tokens / total_input_tokens_est are estimated client-side so
        the UI can warn on soft budgets without charging prelude against the
        history envelope.
        """
        prompt_tokens = 0
        if isinstance(usage, dict):
            try:
                prompt_tokens = int(usage.get("prompt_tokens") or 0)
            except (TypeError, ValueError):
                prompt_tokens = 0
        prelude_est = (
            sum(_estimate_message_tokens(m) for m in prelude) if prelude else 0
        )
        history_est = (
            sum(_estimate_message_tokens(m) for m in history) if history else 0
        )
        return {
            "prompt_tokens": prompt_tokens,
            "budget_tokens": self.history_token_budget,
            "elided_turns": elided_turns,
            "context_window": self.context_window,
            "prelude_tokens": prelude_est,
            "history_tokens": history_est,
            "total_input_tokens_est": prelude_est + history_est,
            "prelude_soft_budget": PRELUDE_SOFT_BUDGET_TOKENS,
            "total_input_soft_budget": TOTAL_INPUT_SOFT_BUDGET_TOKENS,
        }

    def _parse_tool_args(self, raw_args: object) -> dict:
        if isinstance(raw_args, dict):
            return dict(raw_args)
        if isinstance(raw_args, str):
            try:
                parsed = json.loads(raw_args) if raw_args else {}
            except (TypeError, json.JSONDecodeError):
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return {}

    def _approval_gate_request(
        self,
        tool_name: str,
        raw_args: object,
        *,
        source: str = "direct",
    ):
        """Create a pending Approval Gate request, or None if not gated."""
        if self.approval_gate is None or not tool_name:
            return None
        from soveryn.citizens.connectors import requires_approval

        if not requires_approval(tool_name, source=source):
            return None
        from datetime import datetime as _dt

        return self.approval_gate.request(
            citizen=self.agent_name,
            tool=tool_name,
            args=self._parse_tool_args(raw_args),
            now=_dt.now().isoformat(),
        )

    def _approval_denied_message(
        self,
        *,
        tool_name: str,
        approval_id: str,
        state: str,
        call_id: str,
    ) -> ChatMessage:
        result = {
            "error": "ApprovalDenied",
            "tool": tool_name,
            "approval_id": approval_id,
            "state": state,
            "message": (
                "This egress tool call was not approved. "
                "It will not be sent. Re-plan without this call, "
                "or inform the user it was denied."
            ),
        }
        return ChatMessage(
            role="tool",
            content=dump_tool_result(result),
            tool_call_id=call_id,
        )

    def _approval_gate_wait_denied(self, req, *, call_id: str) -> ChatMessage | None:
        """Block on ``req``; return a deny tool message, or None if approved."""
        terminal = self.approval_gate.wait(req.id)
        if terminal.state == "approved":
            return None
        return self._approval_denied_message(
            tool_name=req.tool,
            approval_id=req.id,
            state=terminal.state,
            call_id=call_id,
        )

    def _tool_result_message(
        self,
        tool_call: dict,
        *,
        session_id: str | None = None,
        source: str = "direct",
        skip_approval_gate: bool = False,
        attachments: tuple[str, ...] | None = None,
    ) -> ChatMessage:
        call_id = str(tool_call.get("id") or "")
        function = tool_call.get("function") or {}
        tool_name = str(function.get("name") or "")
        raw_args = function.get("arguments") or "{}"
        args_text = raw_args if isinstance(raw_args, str) else json.dumps(raw_args, sort_keys=True)

        # ── Steering rack pre-dispatch check.
        # If the (session, tool) pair is already tripped, short-circuit with
        # the synthetic error result instead of dispatching. The model sees
        # the tool result naturally and can adjust. Trip status only matters
        # when we have a session_id (production has one; some tests don't).
        if (
            self.steering_rack is not None
            and session_id is not None
            and self.steering_rack.should_short_circuit(
                session_id=session_id, tool_name=tool_name,
            )
        ):
            result = self.steering_rack.synthetic_error(tool_name=tool_name)
            return ChatMessage(
                role="tool",
                content=dump_tool_result(result),
                tool_call_id=call_id,
            )

        # ── Approval gate pre-dispatch check (sync path).
        # Stream path yields ApprovalPendingEvent before wait(); see
        # process_message_stream. Automations auto-pass read-only tools.
        # When skip_approval_gate=True the caller already requested+waited.
        if not skip_approval_gate:
            gated = self._approval_gate_request(tool_name, raw_args, source=source)
            if gated is not None:
                denied = self._approval_gate_wait_denied(gated, call_id=call_id)
                if denied is not None:
                    return denied

        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
        except (TypeError, json.JSONDecodeError) as exc:
            result = {"error": "ToolArgError", "message": str(exc)}
        else:
            # Stamp originating Messages/chat session onto objective_assign so
            # CoS relay delivers the brief into THIS DM, not a random [m] thread.
            if (
                tool_name == "objective_assign"
                and session_id
                and isinstance(args, dict)
                and not str(args.get("dm_session_id") or "").strip()
            ):
                args = dict(args)
                args["dm_session_id"] = session_id
            try:
                from soveryn.platform.intake.turn_images import turn_images_bound

                with turn_images_bound(attachments):
                    result = self.tool_registry.invoke(
                        self.agent_name, tool_name, args,
                    )
            except ToolArgError as exc:
                result = {"error": "ToolArgError", "message": str(exc)}
            except Exception as exc:  # noqa: BLE001 — handler failures must surface
                # Any other tool handler exception (DB lock, transient network,
                # bug in a tool) becomes a tool-result payload the model can
                # see and respond to. Without this, a single tool handler raise
                # crashes the whole turn. BaseException stays unhandled —
                # SystemExit / KeyboardInterrupt propagate as intended.
                result = {"error": type(exc).__name__, "message": str(exc)}

        # ActTruth soft lesson — if this failure continues a streak, tell the
        # model in-band so same-turn retry loops can stop.
        try:
            from soveryn.platform.acttruth.lessons import maybe_lesson_for_tool_result

            ok_flag = not (
                isinstance(result, dict)
                and (result.get("error") or result.get("ok") is False)
            )
            err = None
            if isinstance(result, dict):
                err = result.get("message") or result.get("error")
                if result.get("error"):
                    ok_flag = False
            lesson = maybe_lesson_for_tool_result(
                self.agent_name,
                tool=tool_name,
                ok=ok_flag,
                error=str(err) if err else None,
                result=result,
            )
            if lesson and isinstance(result, dict):
                result = dict(result)
                result["acttruth_lesson"] = lesson
            elif lesson and not isinstance(result, dict):
                result = {"result": result, "acttruth_lesson": lesson}
            # Step 3: park a bug-triage candidate (deduped). Never auto-fixes.
            if lesson:
                try:
                    from soveryn.platform.acttruth.triage import enqueue_if_lesson

                    triage_row = enqueue_if_lesson(
                        agent=self.agent_name,
                        tool=tool_name,
                        lesson_text=str(lesson),
                        error=str(err) if err else None,
                        result=result,
                    )
                    if triage_row and isinstance(result, dict):
                        result = dict(result)
                        result["acttruth_triage_id"] = triage_row.get("id")
                except Exception:
                    pass
        except Exception:
            pass

        result_content = dump_tool_result(result)

        # ── Steering rack post-dispatch observe.
        # observe() handles the watched-tool check internally; opaque tools
        # never trip per is_empty_result's fall-open semantics. The breaker
        # may now be tripped — the next dispatch in the loop sees that.
        if self.steering_rack is not None and session_id is not None:
            self.steering_rack.observe(
                session_id=session_id,
                tool_name=tool_name,
                args_text=args_text,
                result_content=result_content,
            )

        return ChatMessage(
            role="tool",
            content=result_content,
            tool_call_id=call_id,
        )

    def process_message_stream(
        self,
        session_id: str,
        user_message: str,
        attachments: tuple[str, ...] | None = None,
        *,
        source: str = "direct",
    ) -> "Iterator[AgentStreamEvent]":
        """Streaming variant. Yields TokenEvent per content delta, then either
        DoneEvent (success) or ErrorEvent (mid-stream failure). Assistant turn
        saved ONLY on DoneEvent, AND only if upstream sent an explicit
        finish_reason (constraint 5).

        attachments — mirror of process_message: wire-level current user
        message becomes a vision-format list; DB still stores text-only;
        vision-capable agents only (raises AgentLoopError BEFORE save_turn
        otherwise).

        source — mirror of process_message: tags both the user and assistant
        turn's `source` column (default "direct").

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
        if attachments and self.agent_name not in VISION_CAPABLE_AGENTS:
            raise AgentLoopError(
                f"attachments only supported for vision-capable agents "
                f"(agent {self.agent_name!r} has no vision model loaded)"
            )

        # ── Save user turn FIRST (honest state if stream fails later).
        # Text-only by design — vision parts live in-flight, not in the DB.
        self.conv_store.save_turn(
            session_id, self.agent_name, "user", user_message, source=source,
        )
        history_turns = self.conv_store.load_history(session_id)

        continuity_brief = self._build_continuity_brief(session_id)
        recall_context = self._build_recall_context(session_id, user_message)
        identity_context = self._build_identity_context()
        skills_index = self._build_skills_index()

        # ── Build messages
        history_messages = tuple(
            ChatMessage(role=t.role, content=t.content) for t in history_turns
        )
        prelude: tuple[ChatMessage, ...] = ()
        # Same as sync path — semantic layers stay separate; transport adapter
        # folds at wire if the server's template can't honor multi-system.
        if self.system_prompt:
            prelude = prelude + (ChatMessage(role="system", content=self.system_prompt),)
        if continuity_brief:
            prelude = prelude + (ChatMessage(role="system", content=continuity_brief),)
        if self.pinned_text:
            prelude = prelude + (ChatMessage(role="system", content=self.pinned_text),)
        if self.soul_text:
            prelude = prelude + (ChatMessage(role="system", content=self.soul_text),)
        if identity_context:
            prelude = prelude + (ChatMessage(role="system", content=identity_context),)
        if recall_context:
            prelude = prelude + (ChatMessage(role="system", content=recall_context),)
        if skills_index:
            prelude = prelude + (ChatMessage(role="system", content=skills_index),)

        elided_turns = 0
        if self.history_token_budget is not None:
            history_messages, marker, elided_turns = _apply_history_budget(
                prelude, history_messages, self.history_token_budget,
                charge_prelude=False,
            )
            if marker is not None:
                prelude = prelude + (marker,)
        messages = prelude + history_messages
        _usage_prelude = prelude
        _usage_history = history_messages

        # Temporal splice — see sync-path note. Lives on the current user
        # turn so the prelude stays byte-identical across turns.
        temporal_context = self._build_temporal_context()
        last = messages[-1]
        assert last.role == "user", (
            "last message must be the current user turn for the temporal splice"
        )
        spliced_user_text = f"{temporal_context}\n\n{user_message}"
        messages = messages[:-1] + (
            ChatMessage(role="user", content=spliced_user_text),
        )

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
            current_text = last.content if isinstance(last.content, str) else spliced_user_text
            spliced_content: list[dict] = [{"type": "text", "text": current_text}]
            for url in attachments:
                spliced_content.append({"type": "image_url", "image_url": {"url": url}})
            messages = messages[:-1] + (
                ChatMessage(role="user", content=spliced_content),
            )

        # Round loop: streaming generation → maybe tool calls → tool dispatch →
        # next streaming generation, until the model emits a final answer or we
        # hit max_tool_rounds. Mirrors the sync-path semantics in
        # process_message.
        # Black-box recorder — same lifecycle as sync path; idempotent finalize
        # at every termination so failures (timeout, stream error, cap hit,
        # empty generation) all land in the audit trail. No-op when no tools
        # fire, no-op when black_box=None.
        recorder = (
            self.black_box.begin_turn(
                session_id=session_id,
                agent=self.agent_name,
                user_message=user_message,
            )
            if self.black_box is not None else None
        )
        tool_rounds = 0
        final_content_parts: list[str] = []
        final_finish_reason: str | None = None
        final_usage: dict | None = None

        # Verification gate state (Vett-only, self-scoped via _gate_active).
        # For a gate-active turn, content tokens are BUFFERED per round rather
        # than streamed live: the confab must never reach the user, and once
        # tokens are streamed they cannot be un-sent. So for gate-active turns
        # each round's tokens are withheld until the round completes and the
        # gate decides (emit → replay buffered tokens; hold → discard them;
        # floor → replace with the honest floor). For non-gate turns the code
        # path below is byte-for-byte the pre-gate behavior (yield live).
        gate_active = self._gate_active
        turn_tool_ledger: list[str] = []
        verify_budget = (
            self.verification_gate.forced_verify_budget
            if gate_active and self.verification_gate is not None else 0
        )
        # After a gate HOLD, next stream request uses tool_choice=required.
        force_tool_choice: str | None = None
        # After the last allowed tool dispatch, next stream is no-tools final.
        force_final_stream: bool = False
        # Fixed for the whole turn: trivial "hey"/"ok" never see a tool menu.
        turn_tools = self._tools_for_user_turn(user_message)

        while True:
            this_force_final = force_final_stream
            force_final_stream = False  # one-shot
            if this_force_final:
                schemas = None
                stream_messages = self._messages_for_tool_cap_synthesis(messages)
                stream_tool_choice = None
            else:
                schemas = turn_tools
                stream_messages = messages
                stream_tool_choice = (
                    force_tool_choice if (force_tool_choice and schemas) else None
                )
            request = ChatRequest(
                messages=stream_messages,
                model=self.server.model_alias,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                tools=schemas,
                tool_choice=stream_tool_choice,
                thinking_budget_tokens=self.thinking_budget_tokens,
            )
            force_tool_choice = None  # one-shot unless another hold sets it

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
                        # Gate-active turns buffer (don't stream) until the gate
                        # clears this round — see the block header above.
                        if not gate_active:
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
                if recorder is not None:
                    recorder.finalize(
                        final_content="".join(round_content_parts),
                        finish_reason="chat_timeout",
                        usage=final_usage,
                    )
                yield ErrorEvent(code="chat_timeout", message=str(e))
                return
            except LlamaServerError as e:
                if not first_chunk_seen and tool_rounds == 0:
                    raise  # setup error on first round → route returns 502 JSON
                if recorder is not None:
                    recorder.finalize(
                        final_content="".join(round_content_parts),
                        finish_reason="chat_server_error",
                        usage=final_usage,
                    )
                yield ErrorEvent(code="chat_server_error", message=str(e))
                return
            except Exception as e:
                if not first_chunk_seen and tool_rounds == 0:
                    raise
                if recorder is not None:
                    recorder.finalize(
                        final_content="".join(round_content_parts),
                        finish_reason="internal_error",
                        usage=final_usage,
                    )
                yield ErrorEvent(code="internal_error", message=f"{type(e).__name__}: {e}")
                return

            # ── Round ended. Determine success.
            if round_finish_reason is None:
                if recorder is not None:
                    recorder.finalize(
                        final_content="".join(round_content_parts),
                        finish_reason="incomplete_stream",
                        usage=final_usage,
                    )
                yield ErrorEvent(
                    code="incomplete_stream",
                    message="stream closed without finish_reason — no assistant turn saved",
                )
                return

            round_content = "".join(round_content_parts)
            round_tc_tuple = tuple(round_tool_calls) if round_tool_calls else None

            # Force-final stream after the last tool dispatch: never re-dispatch
            # tools even if the model still emits tool_calls (tests / sticky
            # models). Content is the answer. Empty falls through to the
            # tool_round_limit ErrorEvent below (same as pre-fix-final).
            if this_force_final:
                if gate_active and round_content:
                    yield TokenEvent(delta=round_content)
                    _s = sanitize_for_tts(round_content, preserve_outer_whitespace=True)
                    if _s.strip():
                        yield TTSTokenEvent(text=_s)
                final_content_parts.append(round_content)
                final_finish_reason = "tool_round_limit"
                break

            # If the model wants tools and we're within the round budget, dispatch.
            if round_tc_tuple and self.tool_registry is not None:
                if tool_rounds >= self.max_tool_rounds:
                    # Cap hit without a prior force-final (max_tool_rounds=0
                    # edge, or a race). Keep any partial content; mark limit.
                    if gate_active and round_content:
                        yield TokenEvent(delta=round_content)
                        _s = sanitize_for_tts(round_content, preserve_outer_whitespace=True)
                        if _s.strip():
                            yield TTSTokenEvent(text=_s)
                    final_content_parts.append(round_content)
                    final_finish_reason = "tool_round_limit"
                    break

                # Gate-active turns buffered this round's content instead of
                # streaming it. This round ends in tool calls (an intermediate
                # "let me verify" step, not a final claim), so its content is
                # safe to release now — replay the buffered tokens before the
                # tool visibility events.
                if gate_active and round_content:
                    yield TokenEvent(delta=round_content)
                    _s = sanitize_for_tts(round_content, preserve_outer_whitespace=True)
                    if _s.strip():
                        yield TTSTokenEvent(text=_s)

                # Carry the assistant-with-tool_calls message into the next round's
                # context so the model has a coherent transcript.
                messages = messages + (ChatMessage(
                    role="assistant",
                    content=round_content,
                    tool_calls=list(round_tc_tuple),
                ),)

                if recorder is not None:
                    recorder.record_action(
                        round_index=tool_rounds,
                        tool_calls=list(round_tc_tuple),
                        content=round_content,
                    )

                # Record tool names for the verification ledger.
                for _tc in round_tc_tuple:
                    _fn = _tc.get("function") or {}
                    turn_tool_ledger.append(str(_fn.get("name") or ""))

                # Invoke each tool, emit visibility events, append result messages.
                # Approval Gate: request → ApprovalPendingEvent → wait → invoke
                # (or deny tool_result). Yielding before wait lets /chat_stream
                # show Allow/Deny while this thread blocks.
                round_observations: list[dict] = []
                for tool_call in round_tc_tuple:
                    function = tool_call.get("function") or {}
                    call_id = str(tool_call.get("id") or "")
                    tool_name = str(function.get("name") or "")
                    raw_args = function.get("arguments") or ""
                    yield ToolCallEvent(
                        call_id=call_id,
                        name=tool_name,
                        args=str(raw_args),
                    )
                    gated = self._approval_gate_request(
                        tool_name, raw_args, source=source,
                    )
                    if gated is not None:
                        yield ApprovalPendingEvent(
                            approval_id=gated.id,
                            citizen=gated.citizen,
                            tool=gated.tool,
                            args=dict(gated.args),
                            call_id=call_id,
                        )
                        denied = self._approval_gate_wait_denied(
                            gated, call_id=call_id,
                        )
                        if denied is not None:
                            yield ToolResultEvent(
                                call_id=call_id,
                                name=tool_name,
                                content=denied.content,
                            )
                            messages = messages + (denied,)
                            if recorder is not None:
                                round_observations.append(
                                    _build_observation_entry(tool_call, denied)
                                )
                            continue
                        result_message = self._tool_result_message(
                            tool_call,
                            session_id=session_id,
                            source=source,
                            skip_approval_gate=True,
                            attachments=attachments,
                        )
                    else:
                        result_message = self._tool_result_message(
                            tool_call,
                            session_id=session_id,
                            source=source,
                            attachments=attachments,
                        )
                    yield ToolResultEvent(
                        call_id=call_id,
                        name=tool_name,
                        content=result_message.content,
                    )
                    messages = messages + (result_message,)
                    if recorder is not None:
                        round_observations.append(
                            _build_observation_entry(tool_call, result_message)
                        )
                if recorder is not None and round_observations:
                    recorder.record_observation(
                        round_index=tool_rounds,
                        results=round_observations,
                    )

                tool_rounds += 1
                # After the last allowed tool dispatch, next stream is force-final.
                if tool_rounds >= self.max_tool_rounds:
                    force_final_stream = True
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
                # Record the action so the audit trail shows what the model
                # asked for, even though we didn't execute it.
                if recorder is not None:
                    recorder.record_action(
                        round_index=tool_rounds,
                        tool_calls=list(round_tc_tuple),
                        content=round_content,
                    )
                    recorder.finalize(
                        final_content=round_content,
                        finish_reason="no_registry",
                        usage=final_usage,
                    )
                # Gate-active turns buffered this content — release it before the
                # terminal DoneEvent so the user isn't left with content-only.
                if gate_active and round_content:
                    yield TokenEvent(delta=round_content)
                    _s = sanitize_for_tts(round_content, preserve_outer_whitespace=True)
                    if _s.strip():
                        yield TTSTokenEvent(text=_s)
                yield DoneEvent(
                    content=round_content,
                    finish_reason=round_finish_reason,
                    tool_calls=round_tc_tuple,
                    usage=final_usage,
                    context_usage=(
                        self._build_context_usage(
                            final_usage,
                            elided_turns,
                            prelude=_usage_prelude,
                            history=_usage_history,
                        )
                        if self.history_token_budget is not None else None
                    ),
                )
                return

            # No tool calls: this round produced the final answer.
            # ── Verification gate (Vett-only, fail-open). For a gate-active
            # turn the round's tokens are still BUFFERED (never streamed), so a
            # held confab is discarded before it ever reaches the user.
            if gate_active and round_content:
                decision = self._gate_decision(
                    answer_text=round_content,
                    question_text=user_message,
                    tool_ledger=tuple(turn_tool_ledger),
                    budget=verify_budget,
                )
                if (
                    decision is not None
                    and decision.action == "hold"
                    and tool_rounds < self.max_tool_rounds
                ):
                    # HOLD: discard the buffered confab (never emitted), inject
                    # the corrective note, continue for one forced-verify round
                    # with tool_choice=required (API-level force, not just a note).
                    # Bounded by verify_budget → no infinite loop.
                    verify_budget -= 1
                    messages = messages + (ChatMessage(
                        role="system", content=decision.note,
                    ),)
                    force_tool_choice = "required"
                    continue
                if decision is not None and decision.action == "floor":
                    round_content = decision.answer or round_content
            # For a gate-active turn nothing has been streamed yet — release the
            # (gate-cleared or floored) final content now, as one TokenEvent, so
            # the user sees the grounded answer and never the withheld confab.
            if gate_active and round_content:
                yield TokenEvent(delta=round_content)
                _s = sanitize_for_tts(round_content, preserve_outer_whitespace=True)
                if _s.strip():
                    yield TTSTokenEvent(text=_s)
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
                if recorder is not None:
                    recorder.finalize(
                        final_content="",
                        finish_reason="tool_round_limit",
                        usage=final_usage,
                    )
                yield ErrorEvent(
                    code="tool_round_limit",
                    message=(
                        f"model exhausted the {self.max_tool_rounds}-round tool "
                        f"budget without emitting visible content. Reduce task "
                        f"scope or raise max_tool_rounds. No assistant turn saved."
                    ),
                )
            else:
                if recorder is not None:
                    recorder.finalize(
                        final_content="",
                        finish_reason="empty_generation",
                        usage=final_usage,
                    )
                yield ErrorEvent(
                    code="empty_generation",
                    message=f"model produced no visible content (finish_reason={final_finish_reason}); no assistant turn saved",
                )
            return

        self.conv_store.save_turn(
            session_id, self.agent_name, "assistant", accumulated_content,
            source=source, finish_reason=final_finish_reason or "stop",
        )
        self._record_active_exchange(session_id, user_message, accumulated_content)
        if recorder is not None:
            recorder.finalize(
                final_content=accumulated_content,
                finish_reason=final_finish_reason or "stop",
                usage=final_usage,
            )

        yield DoneEvent(
            content=accumulated_content,
            finish_reason=final_finish_reason or "stop",
            tool_calls=None,
            usage=final_usage,
            context_usage=(
                self._build_context_usage(
                    final_usage,
                    elided_turns,
                    prelude=_usage_prelude,
                    history=_usage_history,
                )
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
