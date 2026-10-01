# Aetheria X Presence (One Aetheria) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Give the REAL Aetheria `AgentLoop` a public voice on X — an isolated feed she watches, a heartbeat digest, `read_x`/`post_to_x` tools on her own loop, a conversational approval gate with a trust dial, and lattice memory of what she posts — with the old standalone presence daemon + Signal protocol removed.

**Architecture:** X is capabilities on her existing loop (the one `/chat` + heartbeat use), plus one isolated dumb feed process. Discovery is a separate `soveryn-x-feed.service` writing a candidate feed (SQLite); her loop reads it via a tool + a heartbeat digest; she proposes posts via `post_to_x`; at Stage 0 posts are staged and a deterministic in-thread resolver publishes only on Jon's affirmation; published posts write to her lattice. Trust is a runtime-changeable dial (Stage 0/1/2 + instant panic-to-0).

**Tech Stack:** Python 3.11 (soveryn env), SQLite, `requests`/`requests_oauthlib` (installed), the existing hardened `soveryn/agents/presence/{x_client,scorer,candidate_store,publisher,config}.py`.

## Global Constraints
- **Python 3.11**, tests via `/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest`.
- **Build INTO the real `aetheria` AgentLoop** — no new decision-making loop or clone. The ONLY new process is the dumb feed worker.
- **Honesty invariants (verify each):** at Stage 0 nothing publishes without Jon's affirmation (structural — the tool only stages, the resolver publishes); ambiguous/unrelated reply never publishes; the feed never fabricates; anti-double-post (reuse hardened `publisher`); only *published* posts become recallable `x_post` memory (rejections logged separately).
- **Trust dial is runtime-readable** — a change (incl. panic→0) takes effect on her next turn, no redeploy.
- **One staged post at a time**, with a TTL (default 12h).
- **Deterministic** — no `Date.now()`/random in logic; pass timestamps in.
- Commits: prefix with `GIT_AUTHOR_NAME="Jon de Oliveira" GIT_AUTHOR_EMAIL="jdeoliveira@soverynintelligence.com" GIT_COMMITTER_NAME="Jon de Oliveira" GIT_COMMITTER_EMAIL="jdeoliveira@soverynintelligence.com"`; end each body with `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

## File Structure
```
soveryn/agents/presence/            (repurposed — mechanical pieces STAY)
  x_client.py scorer.py candidate_store.py publisher.py config.py   KEEP (hardened)
  trust.py         NEW  runtime x_trust_stage read + panic
  staged_store.py  NEW  one-at-a-time staged X post: stage/get/resolve/expire, TTL, state
  x_tools.py       NEW  read_x + post_to_x ToolSpecs (post_to_x is trust-stage-gated)
  resolver.py      NEW  in-thread approval resolver (affirm/edit/decline, scoped to the staged post)
  x_memory.py      NEW  write x_post lattice node on publish (published-only); rejection signal log
  digest.py        NEW  build the density-capped heartbeat digest line from the feed
  feed_worker.py   NEW  isolated poll loop (backoff, freshness, health status)
  REMOVE: daemon.py, __main__.py(old), aetheria_bridge.py, inbound.py, pending_store.py,
          approval.py(Signal-format+classify parts)   [Task 12]
soveryn/app/startup.py              register read_x + post_to_x for aetheria; wire trust store   [Task 6]
soveryn/app/routes/chat.py          pre-turn resolver hook                                        [Task 8]
soveryn/agents/heartbeat/daemon.py  splice the digest into her wake                               [Task 11]
soveryn/agents/x_feed/__main__.py   NEW isolated feed-worker entrypoint                            [Task 2]
~/.config/systemd/user/soveryn-x-feed.service   NEW    +   REMOVE soveryn-presence.service        [Task 2/12]
data/x_trust.json                   runtime trust-stage store (live-readable)                     [Task 3]
```

**Deferred reads (inside the task that needs them — the map subagent's output pins these):**
- Task 6: the exact `tool_registry.register(...)` block for an existing aetheria tool in `startup.py`.
- Task 8: the pre-`process_message` insertion point + session id available in `chat.py:179`.
- Task 11: the heartbeat prompt-assembly point in `heartbeat/daemon.py` (`_do_tick`/`_call_vnext_chat`) + the heartbeat's session id.

---

### Task 1: `feed_worker` — isolated poll loop
**Files:** Create `soveryn/agents/presence/feed_worker.py`; Test `tests/agents/presence/test_feed_worker.py`
**Interfaces:**
- Produces: `class XFeedWorker` — `__init__(*, cfg: PresenceConfig, x_client, store: CandidateStore, now_fn)`; `poll_once() -> int` (search mentions + niche, dedup via `store.is_seen`, `score_tweet`, upsert above threshold; returns new-candidate count); `status() -> dict` (`last_ok_ts`, `consecutive_errors`, `stale: bool`); `run_forever(*, interval_seconds, iterations=None, sleep, stop_requested, backoff_base=…)` mirroring the ares interruptible-sleep loop BUT with exponential backoff on `XClientError` (never hammers) and marking `stale` after `cfg` staleness window.
- Consumes: `x_client` (Task-existing), `CandidateStore`, `PresenceConfig`, `score_tweet`.

- [ ] Step 1: failing test — fake x_client returning tweets → `poll_once` upserts scored candidates, skips `is_seen`; a fake raising `XClientError` → `poll_once` records the error in `status()` and does NOT raise; consecutive errors grow the backoff (assert the sleep argument grows).
- [ ] Step 2: run, verify fail.
- [ ] Step 3: implement (mention search first, then niche — preserves `kind="mention"`; backoff = `min(cap, base * 2**consecutive_errors)`; `status()` from counters).
- [ ] Step 4: run, verify pass.
- [ ] Step 5: commit `feat(x): isolated feed worker (poll, backoff, health)`.

### Task 2: feed-worker entrypoint + systemd unit
**Files:** Create `soveryn/agents/x_feed/__main__.py`, `~/.config/systemd/user/soveryn-x-feed.service`; Test `tests/agents/presence/test_x_feed_main.py`
**Interfaces:** `parse_args`, `build_worker` (assembles `PresenceConfig.default()`, `XClient.from_env()`, `CandidateStore(cfg.db_path)`), `run`/`main` mirroring `soveryn/agents/ares/__main__.py` (SIGTERM/SIGINT + `run_forever(stop_requested=…)`).
- [ ] Step 1: failing test — `parse_args` defaults/flags; `build_worker` with monkeypatched env + faked `XClient.from_env` returns an `XFeedWorker` (no network).
- [ ] Step 2-4: TDD implement; write the unit (`Type=simple`, `Restart=on-failure`, `RestartSec=20`, `StartLimitIntervalSec=300`/`Burst=5`, `EnvironmentFile=%h/.config/soveryn/x_presence.env`, `ExecStartPre` readiness on `:5001/health`, `ExecStart python -m soveryn.agents.x_feed --interval-seconds 300`, append log `/tmp/soveryn-x-feed.log`). Do NOT enable it yet.
- [ ] Step 5: commit `feat(x): x-feed entrypoint + systemd unit (isolated process)`.

### Task 3: `trust.py` — runtime trust-stage store + panic
**Files:** Create `soveryn/agents/presence/trust.py`; Test `tests/agents/presence/test_trust.py`
**Interfaces:** `read_trust_stage(path: Path) -> int` (reads `data/x_trust.json` `{"stage": 0}`; missing/malformed → **0**, the safe default — fail-closed, map item 4); `set_trust_stage(path, stage: int)` (atomic write; validates 0/1/2); `panic_to_zero(path)` = `set_trust_stage(path, 0)`. Pure/file-only; read is cheap (called per turn by the tool + resolver, so a write takes effect next turn — no redeploy).
**Panic affordance (how Jon triggers it):** a `__main__` CLI — `python -m soveryn.agents.presence.trust set 0|1|2` and `... panic` — that writes the file. That's the panic button + the dial-turn, one command, effective on her next turn.
- [ ] Step 1: failing test — default 0 when file absent; set→read round-trip; malformed json → 0 (never a higher stage); invalid stage rejected; panic → 0; CLI `set 2` then `read` → 2, CLI `panic` → 0.
- [ ] Step 2-4: TDD implement (atomic temp-file + `os.replace`; argparse CLI).
- [ ] Step 5: commit `feat(x): runtime trust-stage store + panic CLI (safe-default 0)`.

### Task 4: `staged_store.py` — ONE staged post per AGENT (not per session), TTL, state
**Files:** Create `soveryn/agents/presence/staged_store.py`; Test `tests/agents/presence/test_staged_store.py`
**CRITICAL correction (map item 6):** a post proposed during a heartbeat wake lives in the `[heartbeat] aetheria` session, but Jon's approval lands in his PRIMARY thread — different session ids. So the staged post is keyed on the **agent** (a single pending slot for "aetheria"), NOT on session_id. The resolver (Task 7/8) matches Jon's message in his primary thread against that one agent slot.
**Interfaces:** `StagedStore(db_path)`; `StagedPost` dataclass (`id, agent, text, reply_to, proposed_at, state`); state ∈ `proposed|published|rejected|expired`. Methods: `stage(*, agent, text, reply_to, now) -> StagedPost` — **raises `StagedBusyError` if a `proposed` post already exists for that agent** (one-at-a-time); `pending(agent) -> StagedPost|None`; `mark(id, state)`; `expire_stale(now, ttl_hours) -> list[StagedPost]` (proposed → expired past TTL, returns expired ones so callers can note them). No session_id anywhere.
- [ ] Step 1: failing test — stage → `pending("aetheria")` returns it; a second stage while one proposed → `StagedBusyError`; mark published → pending None; `expire_stale` flips an old proposed to expired and leaves a fresh one.
- [ ] Step 2-4: TDD implement (SQLite, deterministic — `now` passed in).
- [ ] Step 5: commit `feat(x): staged-post store (one-per-agent slot, TTL, state)`.

### Task 5: `x_tools.py` — read_x + post_to_x (trust-gated)
**Files:** Create `soveryn/agents/aetheria/tools/x_tools.py` (the aetheria-tools location, map item 1); Test `tests/agents/aetheria/test_x_tools.py`
**Note (map item 1):** tool handlers receive ONLY the validated args dict — **no session_id**. So `post_to_x` stages to the single per-agent slot (`agent="aetheria"`); no session correlation in the handler.
**Interfaces:**
- `build_read_x_tool(*, owner_agent="aetheria", store: CandidateStore) -> ToolSpec` (name `read_x`, optional `limit`, handler returns the ranked feed as dicts — real data or an honest empty list). Adapt the committed `build_read_presence_candidates_tool`.
- `build_post_to_x_tool(*, owner_agent="aetheria", staged: StagedStore, publisher_fn, trust_path, now_fn) -> ToolSpec` (name `post_to_x`, args `{text: str, reply_to?: str}`). Handler logic by `read_trust_stage(trust_path)` (read per-invocation → panic takes effect next turn):
  - **Stage 0** → `staged.stage(agent="aetheria", ...)`; return `"Staged — it posts once Jon says yes."` (never publishes). `StagedBusyError` → return `"You already have a post waiting on Jon; resolve that first."`
  - **Stage 1** → `reply_to` set → **stage** (replies gated); else **publish now** via `publisher_fn` (originals autonomous).
  - **Stage 2** → publish now.
  - Never publishes at Stage 0; publish path uses the hardened `publisher`.
- [ ] Step 1: failing tests — Stage 0 reply+original → staged, publisher NOT called; Stage 1 reply → staged, original → published; Stage 2 → published; busy → friendly message, no second stage; a malformed/missing trust file → treated as Stage 0 (fail-closed).
- [ ] Step 2-4: TDD implement (inject `publisher_fn`, `trust_path`, `now_fn`; fakes in tests).
- [ ] Step 5: commit `feat(x): read_x + trust-gated post_to_x tools`.

### Task 6: register the tools on the REAL aetheria loop
**Files:** Modify `soveryn/app/startup.py`; Test extend `test_app_wiring_contract` (boots real `create_app()` per [[feedback_production_wiring_contract]])
**Map item 1 — exact location + pattern:** the shared `tool_registry = ToolRegistry()` is built at `startup.py:124` and given to every loop at `startup.py:613`. Aetheria-owned tools register inside the `if recall_lattice is not None:` block around `startup.py:143-186` (same block as `register_personal_files_tools(tool_registry, owner_agent="aetheria")` @143 and the delegation tools). Exemplar to copy: `build_deliberate_share_tool` registered at `startup.py:518-525` (`tool_registry.register(build_..._tool(..., owner_agent="aetheria"))`). Construct `CandidateStore`, `StagedStore`, `trust_path`, and the `publisher_fn` here and register both tools.
- [ ] Step 1: **read** `startup.py:124-186` + `:518-525` to confirm the block and the store/embed_fn handles in scope.
- [ ] Step 2: failing test — after `create_app()`, `tool_registry.iter_tools_for_agent("aetheria")` includes `read_x` and `post_to_x`, and `iter_tools_for_agent("vett")` / `"scotty"` do NOT.
- [ ] Step 3-4: implement + pass.
- [ ] Step 5: commit `feat(x): register read_x + post_to_x on the real aetheria loop`.

### Task 7: `resolver.py` — approval resolver (agent-slot, not session)
**Files:** Create `soveryn/agents/presence/resolver.py`; Test `tests/agents/presence/test_resolver.py`
**Interfaces:** `classify_affirmation(text) -> "affirm"|"edit"|"decline"|"unrelated"` (affirm only on clear tokens; decline on clear no; **unrelated/ambiguous is its own bucket → never publishes**). `resolve_pending(*, agent="aetheria", message, staged: StagedStore, publisher_fn, x_memory_fn, rejection_fn, now) -> ResolveResult|None`: look up `staged.pending(agent)` (the single per-agent slot — NOT session-keyed, map item 6). None → return None (normal turn proceeds). Else classify `message`: **affirm** → publish via `publisher_fn`, `staged.mark(published)`, `x_memory_fn(...)`, return a `[posted to X: <url>]` note; **edit** → keep the post proposed, return revision-handoff (her normal turn runs with the edit as context, she re-proposes); **decline** → `staged.mark(rejected)` + `rejection_fn(...)`, return a "dropped" note; **unrelated** → return None (post stays proposed, her normal turn runs — an unrelated message must NEVER publish).
- [ ] Step 1: failing tests — pending + affirm → one publish + x_memory called + note; pending + unrelated ("hold on, other thing") → None, NO publish, post still proposed; pending + decline → rejected + rejection_fn, no publish; no pending → None.
- [ ] Step 2-4: TDD implement (bias-to-safety: default bucket is unrelated; empty/whitespace → unrelated).
- [ ] Step 5: commit `feat(x): approval resolver (agent-slot, affirm-only publishes)`.

### Task 8: chat-path pre-turn hook (BOTH /chat and /chat_stream)
**Files:** Modify `soveryn/app/routes/chat.py`; Test `tests/app/test_chat_resolver_hook.py`
**Map item 3 — TWO entry points:** `chat()` (`chat.py:178-233`, calls `loop.process_message` @209) AND `chat_stream()` (`chat.py:282`, calls `process_message_stream` @313). A hook in only `chat()` would be BYPASSED by the desktop UI, which streams. So add a shared helper and call it from BOTH before the loop. Session id is `body.get("session_id")` (@188); `_state()` (`chat.py:100`) holds the stores.
- Helper `maybe_resolve_x_approval(*, agent, message, state) -> ResolveResult|None`: only for `agent=="aetheria"`; calls `resolve_pending(agent="aetheria", message=message, staged=state["x_staged"], …)`. It is **agent-slot keyed, so it fires regardless of which session Jon replies in** (his primary thread) — closing the heartbeat/primary split (map item 6).
- In each route: before the loop, if the helper returns a ResolveResult → return it to the client and DON'T run her normal turn (a bare affirm's whole meaning was "post it"); if None → proceed unchanged (unrelated/edit/no-pending flow into her real turn).
- **Guard against the heartbeat path:** the heartbeat also POSTs `/chat` (map item 2) but its message is a `[HEARTBEAT]` brief, never an affirm — classify handles it (→ unrelated → None), so it flows into her normal wake untouched.
- [ ] Step 1: **read** `chat.py:100,178-233,282-313` to confirm both call sites + `_state()` shape.
- [ ] Step 2: failing tests — pending + affirm via `chat()` → publishes, no normal turn; pending + affirm via `chat_stream()` → publishes; normal message, nothing staged → the loop runs as before (both routes); a `[HEARTBEAT]` message with a post pending → NOT published, loop runs.
- [ ] Step 3-4: implement (shared helper, called from both) + pass.
- [ ] Step 5: commit `feat(x): resolver hook on /chat + /chat_stream (affirm publishes before her turn)`.

### Task 9: `x_memory.py` — published-only lattice writes (WITH embedding)
**Files:** Create `soveryn/agents/presence/x_memory.py`; Test `tests/agents/presence/test_x_memory.py`
**CRITICAL (map item 5):** recall surfaces a node ONLY if it was written WITH an `embedding` (else it's stored NULL and is keyword-findable but does NOT appear in her per-turn `find_nodes_by_embedding` recall). So the `x_post` node MUST be written with `embedding=embed_fn(text)`. Omitting it makes her posts un-remembered — the exact opposite of the point.
**Interfaces:** `write_x_post_node(*, lattice_store, embed_fn, agent="aetheria", text, source_tweet, edited_by_jon, posted_id, now) -> str` — `lattice_store.write_node(agent, text, node_type="x_post", tags=("x","post"), embedding=embed_fn(text), provenance={source, her_text, jon_edit, posted_url})` (signature `legacy.py:462`, layer default private, intensity in range). `log_rejection(*, signal_path, text, reason, now)` — writes the coaching signal to a SEPARATE store, NOT a lattice node (rejections are not recallable public voice).
- [ ] Step 1: failing tests — publish path writes exactly one `x_post` node **with a non-null embedding** (assert `embed_fn` was called with the text and the stored node has the vector); rejection writes to the signal store and creates NO lattice node.
- [ ] Step 2-4: TDD implement (inject `embed_fn` — the same `embed_fn` aetheria's loop uses, in scope at `startup.py`; fake in tests).
- [ ] Step 5: commit `feat(x): published-only x_post lattice memory (embedded, recallable) + rejection log`.

### Task 10: `digest.py` — density-capped heartbeat digest
**Files:** Create `soveryn/agents/presence/digest.py`; Test `tests/agents/presence/test_digest.py`
**Interfaces:** `build_digest(store: CandidateStore, *, top_n=3) -> str|None` — returns one qualitative line (e.g. `"X: a few new mentions, one thread on local-LLM reliability."`) naming the top ~2-3 salient items and bucketing the rest as a count; **no directive language**; empty feed → None (omit). A busy feed never renders raw "50 new mentions."
- [ ] Step 1: failing tests — 2 items → names them; 50 items → qualitative bucket, no raw count, no "you should"; empty → None.
- [ ] Step 2-4: TDD implement.
- [ ] Step 5: commit `feat(x): capped qualitative heartbeat X digest`.

### Task 11: splice the digest into the heartbeat wake
**Files:** Modify `soveryn/agents/heartbeat/prompt.py` + `soveryn/agents/heartbeat/daemon.py`; Test the heartbeat prompt test
**Map item 2 — exact splice:** the brief is built by `build_heartbeat_prompt(...)` at `prompt.py:43-127` (lines list @72-126, joined @127); `_do_tick` calls it at `daemon.py:307-314` after it already has `board`/`lattice`/`material_signals`. Add an `x_digest: str = ""` kwarg to `build_heartbeat_prompt`, append `lines.append(f"- X: {x_digest}")` in the orientation block near the Lattice line (`prompt.py:92-98`) when non-empty; in `_do_tick`, compute `x_digest = build_digest(candidate_store) or ""` (reads the same feed the tool reads) and pass it through.
- [ ] Step 1: **read** `prompt.py:43-127` + `daemon.py:307-314` to confirm the kwarg/append spot.
- [ ] Step 2: failing test — `build_heartbeat_prompt(..., x_digest="a few mentions")` includes the `- X:` line; `x_digest=""` adds no line.
- [ ] Step 3-4: implement + pass.
- [ ] Step 5: commit `feat(x): heartbeat X digest splice (bare, on wake)`.

### Task 12: remove the fragmenting daemon + Signal protocol
**Files:** Delete `soveryn/agents/presence/{daemon.py, __main__.py(old), aetheria_bridge.py, inbound.py, pending_store.py}` + the Signal-format/classify parts of `approval.py` + their tests; revert the `signal_bridge/daemon.py` Phase-2b hookup + the `soveryn-signal-bridge.service` `SIGNAL_USER_NUMBER` env line; remove `~/.config/systemd/user/soveryn-presence.service`.
- [ ] Step 1: confirm nothing in the KEPT set imports the removed modules (grep); adjust any stragglers.
- [ ] Step 2: delete + run the FULL presence suite + the signal_bridge suite green (the remaining `x_client/scorer/candidate_store/publisher/config` + new modules pass).
- [ ] Step 3: revert the bridge edits (restore its pre-Phase-2b `_handle_inbound`; drop the added `SIGNAL_USER_NUMBER` line), `daemon-reload`, restart bridge, confirm active.
- [ ] Step 4: commit `refactor(x): remove standalone presence daemon + Signal draft protocol (one Aetheria)`.

### Task 13: rig test (manual, real creds) — the first real post
**Files:** `tests/agents/presence/test_x_rig.py` (`@pytest.mark.rig`, opt-in)
- [ ] One end-to-end at Stage 0: feed finds a tweet → `read_x` shows it → `post_to_x` stages → simulate Jon's affirm → publishes to @Soveryn_AI → an `x_post` lattice node exists. Run manually with creds; not in CI.
- [ ] Commit `test(x): opt-in rig test for the staged→approve→post→memory loop`.

## Self-Review
- **Coverage:** feed (T1/T2), trust dial + panic (T3), staged one-at-a-time+TTL (T4), tools trust-gated (T5), registered on real loop (T6), resolver affirm-only (T7), chat hook (T8), published-only memory (T9), capped digest (T10/T11), removal of the clone/daemon (T12), rig (T13). Every spec component + accepted review fix maps to a task.
- **Deferred reads** (T6/T8/T11) are explicit read-first steps, not placeholders.
- **Type flow:** `CandidateStore` (feed) → `read_x`/`digest`; `StagedStore` → `post_to_x`/`resolver`/`chat hook`; `trust_path` → `post_to_x`; `publisher_fn` → `post_to_x`/`resolver`; `LatticeStore` → `x_memory`.

## Execution Handoff
Plan saved. Two options: **(1) Subagent-Driven (recommended)** — fresh subagent per task, review between, cheap model for T1/T3/T4/T10, standard for T5/T7/T9, standard+read for the integration tasks T6/T8/T11/T12; **(2) Inline**. Which?
