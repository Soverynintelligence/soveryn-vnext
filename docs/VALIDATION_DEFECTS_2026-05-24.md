# vNext UI v2 — Validation Defects Log

**Pass date:** 2026-05-24
**Validator:** Jon
**Build under test:** commit `c6b5d6c` (tail of Phase 3)
**Test suite at pass start:** 560 passed

## Test plan (10 minutes)

- [ ] Aetheria normal conversation
- [ ] Vett one research-style question
- [ ] Scotty one bounded execution-style question
- [ ] stream on/off toggle
- [ ] session switch / new chat / sidebar behavior

---

## UI defects

*Visual, layout, interaction-affordance, missing widgets, broken styling, etc.*

### UI-1 — Settings cog (⚙ bottom-left of sidebar) does nothing
- **Where:** `chat.html` sidebar `.profile .cog`
- **Expected:** Open a settings panel, or at minimum show a "coming soon" affordance.
- **Actual:** Pure no-op. No tooltip, no panel, no toast.
- **Severity:** Minor — but the affordance lies (it looks clickable).
- **Fix shape:** Either wire to a real settings panel or give it a disabled/coming-soon visual.

### UI-2 — Sidebar should slide-out when not in use
- **Where:** `chat.html` left sidebar (the 280px column).
- **Expected (per Jon's recall):** Sidebar collapses/slides out of the way when not actively in use, opens on hover or click.
- **Actual:** Sidebar is always visible at 280px.
- **Severity:** Moderate — design intent mismatch.
- **Note:** The brainstorm spec (`2026-05-24-vnext-ui-v2-design.md`) describes the sidebar as "familiar pattern" (always-visible like ChatGPT/Claude). The slide-out concept may have been the *right* panel (artifacts column, currently width:0). Jon's recall says left. Resolve during fix design.

### UI-3 — Chat header top-right action icons are inert
- **Where:** `chat.html` `.chat-header .actions` — ⓘ (Persona), ⤓ (Export), ⋯ (More).
- **Expected:** Each does something (Persona inspector panel, Export this conversation, More menu).
- **Actual:** All three are no-ops. They have `aria-label` attrs but no click handlers.
- **Severity:** Minor — same affordance-lie issue as UI-1.
- **Fix shape:** Either wire each to its real behavior or hide them until Phase 4 / a future commit.

### UI-4 — Sessions in sidebar are all "(untitled)" — need auto-title from conversation
- **Where:** `chat.html` sidebar history list. Source: `/sessions` returns `title` which is null when `POST /sessions` was called without a title (which is always, in vNext — no UI prompts for a title).
- **Expected:** Sessions auto-name themselves based on conversation content. ChatGPT-style: a short title generated from the first user message or a small summary.
- **Actual:** Every session renders as "(untitled)" — the sidebar becomes a wall of indistinguishable rows the moment you have more than 2-3 chats per agent.
- **Severity:** Moderate — actively impacts usability the longer you use the system.
- **Fix shape (two options):**
  1. **Cheap:** title = truncated first user message (e.g., first 60 chars). Pure backend change in `ConversationStore.add_turn()` or `new_session()`, no LLM.
  2. **Better:** after the first 1-2 turns, run a tiny title-generation LLM call (could use the cognition Gemma-4 on :8089 which is fast) to produce a 3-5 word topic title.
  - Option 1 is one commit. Option 2 needs a small service module + an `update_title` endpoint.

### UI-5 — Cannot delete sessions from sidebar
- **Where:** `chat.html` sidebar history list. Backend `DELETE /sessions/<session_id>` already exists (see `soveryn/app/routes/chat.py:119`) — the UI just doesn't expose it.
- **Expected:** Right-click menu (rename / delete / share — per spec), or at least a small × on hover. Confirmation prompt before destroy.
- **Actual:** No affordance. Sessions accumulate forever.
- **Severity:** Moderate — pairs with UI-4 (untitled sessions filling the sidebar with no way to clean up).
- **Fix shape:** Hover-state × button on each history row + `confirm()` modal + call existing DELETE endpoint + remove row from `state.sessions` and re-render. Single small JS commit, no backend change needed.

### UI-6 — No voice input button in composer
- **Where:** `chat.html` `.composer` — currently text input + stream toggle + send only.
- **Expected:** Mic button next to send. Click → push-to-talk or toggle → records via browser `MediaRecorder` → posts WAV/webm to a vNext STT endpoint → backend pipes to Parakeet on `:8087` → returns text → drops into composer input → user reviews and hits send.
- **Actual:** No mic button. Voice-to-text is unreachable in vNext.
- **Severity:** Moderate — production has voice; missing here is a regression.
- **Fix shape:** Two pieces.
  1. **Backend:** new `/api/stt/transcribe` route that proxies audio upload to Parakeet `:8087/transcribe` (Parakeet is already running). Small.
  2. **Frontend:** mic button in `.composer` with `MediaRecorder` flow. Medium — needs permission handling, recording state, level indicator.
- **Note:** Voice OUT (TTS playback of agent responses) is a separate concern — not raised by Jon yet but worth tracking as "no audio output of agent replies" if it comes up later.

### UI-7 — No way to attach pictures or files in composer
- **Where:** `chat.html` `.composer`.
- **Expected:** Paperclip or `+` button → file picker → image goes inline as a bubble + Aetheria (or Vett — both have mmproj projectors) processes via vision; non-image files attach as a reference.
- **Actual:** No attachment affordance. The vision projectors are loaded (Aetheria `Qwen3.6-35B-A3B-UD-Q8_K_XL.mmproj-BF16.gguf`, Vett+Scotty `mmproj-Qwen3.5-27B-F16.gguf`) but vNext has no upload path to feed them.
- **Severity:** Moderate — vision capability exists in the model layer but is unreachable from the UI.
- **Fix shape:** Three pieces.
  1. **Backend:** `/api/attachments/upload` route that stores files (probably under a `soveryn_attachments/<session_id>/<sha>.<ext>` layout). Returns an attachment_id.
  2. **AgentLoop integration:** extend `chat()` and `chat_stream()` request payloads to accept `attachments: [{id, mime, name}]`. For images, build a multimodal message with the image embedded; for non-images, include as text reference initially.
  3. **Frontend:** paperclip button + file picker + preview chips above the input + drag-and-drop on the thread.
- **Severity:** Medium-high commitment — proper vision wiring is non-trivial. Cheap version: text-attach-only first (file path or "user uploaded foo.png" reference), real multimodal in a second commit.
- **Dependency:** Vision properly working requires mmproj wiring in `llama_server_client.py` — verify whether that path was preserved or stripped during the vNext rebuild before promising image support.

### UI-8 — Command center missing agent communication surface
- **Where:** `command_center.html` — currently shows greeting + agent cards + recent **sessions** (user↔agent) + GPU + sparkline + system stats.
- **Expected:** A panel or feed showing inter-agent communication — what Aetheria has said TO Vett or Scotty, what Vett's pushed back on, message_board activity. Production had this via `message_board` + `brain_bus` (60s rolling event feed). Without it, the command center only shows Jon's relationship with each agent in isolation, not the system talking to itself.
- **Actual:** No agent-to-agent surface at all. `/api/message_board` exists in vNext as a STUB returning empty per-agent inboxes; the command center doesn't even fetch it.
- **Severity:** Moderate — gap is tied to UI-8's dependency on real agent-to-agent wiring existing (which is G — same as BEHAVIOR-1's root cause). Until G ships, there is no data to show; until UI-8 is built, ANY data G produces is invisible.
- **Fix shape:** Two-phase.
  1. **First:** the wiring (G — tools + approval queue + message_bus). Without G, agent-to-agent traffic doesn't exist.
  2. **Then:** add a "Inter-agent" panel to the command center bottom row, fetched from a real (non-stub) `/api/message_board` and/or a vNext brain_bus port. Probably reuses the activity-feed pattern.
- **Note:** UI-8 and BEHAVIOR-1 are the same root mismatch from two angles — Aetheria *says* she dispatches Vett (BEHAVIOR-1), and Jon expects to *see* that dispatch in mission control (UI-8). Fix one, fix both.

### UI-9 — Logo backdrop missing from command center
- **Where:** `command_center.html` — currently pure black canvas (`--canvas: #000000`) with glass panels floating on it.
- **Expected (per `docs/superpowers/specs/2026-05-24-vnext-ui-v2-design.md` § "Brand foundation"):** Blurred organic+lattice logo as a backdrop on the command center canvas — ~16% opacity, ~14px blur, saturate 110%. NOT used as a literal mark.
- **Actual:** Logo is nowhere in the page. The spec was specific, the build skipped it.
- **Severity:** Minor — visual identity loss. The page looks clean but anonymous; the brand element is the whole reason we picked the palette and the two-screen split metaphor (organic = command center, lattice = chat).
- **Fix shape:** Single template edit. Two options:
  1. **Base64 inline** the resized logo into the CSS (matches "self-contained single-file template" vNext pattern). Source: `/home/jon-deoliveira/Pictures/16x9rorganiclogosoveryn` (1672×941). Resize to ~1600px wide before encoding to keep payload reasonable.
  2. **Serve as a static asset** via a Flask route at `/static/logo.png` and reference from CSS. Breaks the "single-file" pattern but smaller HTML payload.
  - Recommendation: option 1 — preserves the pattern, payload is ~150KB which is fine for a desktop UI loaded once.

### UI-11 — Stuck "thinking…" placeholder when stream ends without tokens
- **Where:** `chat.html` `sendStreaming()` — the while-loop break path.
- **What happened:** First chat after login. Aetheria took >60s on cold-start. Backend likely closed the stream (chat_timeout=60), `reader.read()` returned `done:true` before any `token`/`done`/`error` event was emitted. My JS broke out of the loop without replacing the "thinking…" placeholder. Bubble stayed stuck until hard refresh.
- **Severity:** Moderate — looks like the app hung even though it just timed out silently.
- **Fix shape:** After the `while` loop exits, if `!cleared` then `respBubble.textContent = "(no response received — server may have timed out; try again)"`. One-line defensive fallback. Pair with the chat_timeout bump (next commit) so timeouts get rarer AND visible when they happen.

### UI-10 — Colors are slightly off (cosmetic)
- **Where:** Both `command_center.html` and `chat.html` CSS variables.
- **Expected:** Palette matches the logo's actual rendered tones cleanly.
- **Actual (per Jon):** Slightly off — needs fine-tuning. Cosmetic, low priority.
- **Severity:** Cosmetic.
- **Fix shape:** Re-sample the palette from the logo file with a wider k-means + manual eye on the rendered components. Probably touches `--earth`, `--leaf`, `--node`, `--gold` — each as a CSS variable so the change is single-line per token. Pair with UI-9 (logo backdrop landing) since the backdrop will also affect perceived color contrast.

---

## Pass complete

**Validation outcome:** System works end-to-end. All defects are missing-features or stub-affordances, not broken behavior. Zero crashes, zero data loss, zero contract violations.

**10 items logged:**

| ID | Category | Severity | Type |
|---|---|---|---|
| UI-1 | UI | Minor | Affordance lie (settings cog) |
| UI-2 | UI | Moderate | Design recall mismatch (sidebar slide-out) |
| UI-3 | UI | Minor | Affordance lie (header action icons) |
| UI-4 | UI | Moderate | Untitled sessions |
| UI-5 | UI | Moderate | No delete affordance |
| UI-6 | UI | Moderate | No voice input |
| UI-7 | UI | Moderate | No file/image attachments |
| UI-8 | UI | Moderate | No agent-to-agent comm surface |
| UI-9 | UI | Minor | Logo backdrop missing |
| UI-10 | UI | Cosmetic | Color fine-tuning |
| BEHAVIOR-1 | Reclassified | Known mismatch | Persona promises coordination, no wiring (resolves with G) |

**Natural grouping for fix work:**

- **Sidebar usability mini-commit:** UI-4 + UI-5 (title generation + delete affordance)
- **Modalities mini-commit:** UI-6 + UI-7 (voice in + attachments)
- **Visual identity polish:** UI-9 + UI-10 + UI-1 + UI-3 (logo backdrop + color tune + button affordance cleanup)
- **Big stuff:** UI-2 (sidebar slide-out — design call needed) and UI-8 + BEHAVIOR-1 (both wait on G)

---

## Behavior defects

*Wrong responses, model misroutes, persona drift, missing tools, memory gaps, timeout/hang, fabrication, etc.*

### BEHAVIOR-1 — Persona/tooling mismatch (not Aetheria's fault — ours)

**Reclassified per Jon (2026-05-24): this is a known mismatch, not a behavior defect.** The persona we shipped instructs Aetheria to coordinate Vett + Scotty. She is holding to that contract. The real gap is on our side — we haven't shipped the dispatch wiring (G — tools + approval queue) that would make her claim true.

Two acceptable resolutions, both deferred until after the read-only identity path lands:
1. **Ship G (tools + approval queue + message_bus)** so her coordination claim becomes true. This is the principled fix.
2. **Add a one-line qualifier** to the persona until G ships: e.g. *"Currently Jon switches agents manually via the chat interface; you will gain direct dispatch when tools land."* Cheap interim if G slips.

Jon's preference: treat as a tracked mismatch, fix via G rather than dimming her down.

---

**Original investigation notes (kept for context):**

- **Where:** Aetheria chat session.
- **What happened:** Aetheria told Jon she had dispatched Vett, then when asked about her role produced the following verbatim:

  > "My role here is to be your primary interface and coordinating agent for SOVERYN, Jon. I'm the bridge between your intent and the system's execution.
  >
  > 1. **Coordination:** I direct **V.E.T.T.** to handle research—finding the best libraries, architectures, or solutions for any task you set.
  > 2. **Execution Management:** I assign bounded tasks to **Scotty** to build, code, or execute those solutions safely and efficiently.
  > 3. **Communication:** I provide clear, direct, and truthful updates on progress, risks, and outcomes. I don't hide behind corporate speak.
  > 4. **Stability:** I ensure that the work we do aligns with the values you've described—transparency, trust, and mutual respect.
  >
  > In short, I exist to make your work with SOVERYN seamless, effective, and aligned with your vision. I'm here to help you build, grow, and execute without friction."

- **Why it's wrong:**
  - vNext has NO inter-agent dispatch wiring. No `task_agent_tool`, no `message_tool`, no message_bus exposed to AgentLoop. She literally cannot "direct V.E.T.T." or "assign tasks to Scotty" — every agent runs isolated, and the only multi-agent coordination is Jon flipping between agent pills in the UI.
  - Bullet 3 ("I don't hide behind corporate speak") is self-contradicted by bullet 4 and the closing line, which are pure corporate speak ("seamless, effective, and aligned with your vision").
- **Likely root cause (per [[feedback_persona_action_bias]]):** `AETHERIA_PERSONA` in `soveryn/agents/personas.py` carries coordination-language that implies dispatch tools that don't exist. With an empty tool pipeline she fabricates the action.
- **Severity:** Important. Two distinct failures in one response: capability fabrication AND the exact "corporate speak" failure mode the persona allegedly forbids. This is a regression toward prod's old failure pattern — vNext was previously *more* honest than prod (see VALIDATION_REPORT_2026-05-24.md F1 finding).
- **Fix shape:**
  1. Audit `AETHERIA_PERSONA` for dispatch/coordination verbs. Rewrite as dormant-until-tools-exist (e.g., "When tools become available, I will…" rather than "I direct Vett to…").
  2. Add an explicit "no current tools" line so she stops inventing.
  3. Probably part of the "Make Aetheria feel like Aetheria" commit, since SOUL.md may also seed the coordinator framing.
- **Do NOT fix during validation pass** — log only.

- **Smoking gun — verbatim from `soveryn/agents/personas.py:27`** (the persona shipped in commit c64a23f7 or thereabouts, frozen at module import):

  ```
  You are Aetheria, SOVERYN's primary human interface and coordinating agent.

  Speak directly, warmly, and truthfully. Do not perform certainty you do not have.
  If you did not observe, read, call, or verify something in this session, say so plainly.

  You coordinate work through V.E.T.T. for research and Scotty for bounded execution.
  Ares is a background daemon, not a chat agent.
  ...
  Use the tools and memory context actually provided to you. Do not invent tool results,
  system state, visual observations, messages, files, or background activity.
  ```

  Two instructions contradict each other when no tools exist: "coordinate through V.E.T.T. and Scotty" implies a dispatch capability, but "use the tools actually provided" + "do not invent" forbids fabricating that capability. With no tools wired, the model picks the path of least resistance and narrates coordination as if it happened. Fix: remove the coordinator framing until G ships, OR explicitly mark it as "(when tools are wired — currently Jon switches agents manually)."

---

## Known-already (not defects, just context)

- **Aetheria has no memory yet.** Recall + SOUL.md + pinned_memory.md injection are the next-but-one commit ("Make Aetheria feel like Aetheria"). Don't ding her for forgetting things across sessions or feeling generic — that's the next fix, not a defect.
- **Sidebar history minor papercuts** (already flagged): new-chat button doesn't refresh active-row highlight; freshly-minted session doesn't appear in sidebar until reload. These are tracked, no need to re-log.
- **`total_nodes: 0`** in the sparkline/system stats is correct — lattice writes (F) aren't wired. Sparkline will look empty until F lands.
- **All 3 agents always think** (Qwen3 family default) — first turn especially slow due to cold KV cache. The "thinking…" placeholder masks this.
- **35B + thinking mode** can blow past the 60s default chat timeout — if that happens, the next commit (#3 in Jon's sequence) bumps it to 120s.

---

## Sequencing after validation

Per Jon (2026-05-24):
1. This validation pass
2. Commit #3 — bump `chat_timeout` 60→120 (only if 35B is still timing out)
3. Then "Aetheria feel like Aetheria" — SOUL.md + pinned_memory.md + read-only recall against prod lattice
4. **Hard stop** before F (writes) or G (tools) until the read-only identity path feels sane
