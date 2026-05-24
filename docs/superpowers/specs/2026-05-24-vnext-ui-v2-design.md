# SOVERYN vNext UI v2 — Design Spec

**Date:** 2026-05-24
**Status:** Design locked, implementation pending
**Predecessor:** vNext basic UI at `/` (commit `e2289d7`) — to be replaced
**Brainstorm session:** `/home/jon-deoliveira/soveryn_vnext/.superpowers/brainstorm/1489011-1779630905/`

## Goal

Replace the current basic vNext UI (commit `e2289d7`) with a two-screen system that:

1. **Tells you what to do** when you open it (command center), not just what's true.
2. **Gets out of the way** when you're talking (chat), using conventions people already know.
3. **Reflects the SOVERYN brand** (new organic+lattice logo, dark palette, glass aesthetic).
4. **Names the memory architecture honestly** (Cathedral, Main lattice, Attic, Visual) so future memory work has a shared vocabulary.

This is the first vNext UI commit where the artifact stops being "functional minimum" and starts being something Jon wants to live in.

## Non-goals

- Lattice visualization screen — deferred to its own focused brainstorm + commit. The four-region architecture is named here; the *visualization* of those regions is not designed here.
- Attic implementation — concept and storage model named; actual schema/code is a later commit.
- Visual memory implementation — principle ("storage → meaning") and node shape (`{image, embedding, why}`) named; CLIP / multimodal embedding wiring is a later commit.
- Right-side artifacts panel — layout reserves space (third grid column at width 0) but content/behavior is deferred.
- Mobile responsive — desktop-first; mobile is a separate pass.

---

## Brand foundation

### Logo

- **Source file:** `/home/jon-deoliveira/Pictures/16x9rorganiclogosoveryn` (1672×941, true widescreen, May 23 22:46)
- **Symbolism:** organic tree (left) + lattice constellation (right) — the duality maps directly to the two-screen split (command center = organic/identity; chat = lattice/connection)
- **Tagline:** "LEARN · ADAPT · REMEMBER"
- **Where used:** blurred backdrop on command center canvas (~16% opacity, ~14px blur, saturate 110%); not used as a literal mark in the UI

### Palette

8 colors, extracted from the actual logo file via k-means + green-region resample:

| Token | Hex | Role |
|---|---|---|
| `--canvas` | `#000000` | Page background (80%+ of logo is pure black; UI background is decided) |
| `--earth` | `#4e2d11` | Command-center accent (organic side — memory, identity) |
| `--leaf` | `#455142` | Subtle muted green for Scotty / consolidation / "leaf" agents |
| `--slate` | `#2a4459` | Chat-side panel base (lattice side — network, retrieval) |
| `--node` | `#75cbe8` | Activity color (streaming tokens, live indicators, "alive" states) |
| `--bronze` | `#986d42` | Warm secondary for tags and earth-side highlights |
| `--gold` | `#af9a6d` | Wordmark + brand-level typography accent (sparingly) |
| `--text` | `#ecf3f4` | Primary text |

CSS variables exposed as `--canvas`, `--earth`, `--leaf`, etc. so the values are themable in one place.

### Aesthetic

- **Glass on dark.** All panels use `backdrop-filter: blur(18-24px) saturate(140%)` over `rgba(20,24,32,0.55-0.7)` with `1px solid rgba(255,255,255,0.06)` borders. Soft, layered, depth-by-blur.
- **Rounded corners.** `border-radius: 14-22px` depending on element size. No sharp corners anywhere.
- **Typography.** System font stack: `-apple-system, BlinkMacSystemFont, "SF Pro Display", Inter, sans-serif`. Sizes 9-20px depending on hierarchy; tabular-nums for stats.
- **No external CDN resources.** Self-contained single-file HTML, same constraint as v1.

---

## Two-screen architecture

vNext gets two top-level routes:

- **`/`** — Command Center (Mission Control)
- **`/chat`** — Chat
- **`/legacy`**, **`/legacy/mobile`** — legacy bridge unchanged
- **`/api/...`** — REST surface unchanged

Navigation between the two:
- Command center → Chat: a `→ chat` pill in the top-right header, **and** each agent card on the command center is a direct link to chat with that agent.
- Chat → Command center: a quiet `⌂ mission control` link in the top-right of the chat sidebar.

There is **no** in-page toggle that swaps between command-center and chat in the same browser tab; they are distinct routes. (Browser back/forward works correctly; deep-linking to a chat session works.)

---

## Command Center (`/`)

### Purpose

When Jon opens this screen, the answer to **"what now?"** must be obvious in ≤2 seconds. The screen *guides* him toward action; it does not just *inform*.

### Layout (top to bottom)

1. **Header bar** (padded)
   - Left: `SOVERYN` wordmark in gold
   - Right: status pill (green/amber/red dot · "all systems quiet" or "needs attention")
   - No `→ chat` button here — each agent card is the chat-entry instead

2. **Greeting block** (glass panel)
   - Large: `Morning, Jon.` (time-of-day adaptive)
   - Below: 1-3 sentence narrative of what happened while he was away, in plain English
     ("Aetheria wrote 3 notes about X last night. Vett finished one research task at 04:11. Scotty has no active work. Ares-daemon last scanned at 06:00 and found nothing.")
   - Source: derived from recent conversation_store turns + lattice writes + dream-daemon timestamps + ares state — composed at request time by a small `narrative.py` module (not by an LLM call).

3. **Agent row** (3 glass cards, equal width)
   - Each card: pulsing colored disc (Aetheria gold, Vett cyan, Scotty leaf) + name + one-line role + current state
   - Hover lifts the card slightly; click → goes to `/chat?agent=<name>` and opens a new session OR most-recent session for that agent
   - The pulsing ring is CSS-only animation; subtle enough to not distract, present enough to feel alive

4. **Bottom row** (2 columns, 1.6fr / 1fr)
   - **Left: Recent activity feed** — narrative-style, last 4-6 events. "vett finished researching X — 2 sources cited" beats "1 task complete · 2 sources cited." Each line has timestamp + agent-colored "who" + plain English. Below the feed: a 14-bar memory-writes-per-day sparkline (cyan).
   - **Right: Visual system panel** — 3 GPU bars (utilization% with temperature-gradient fill), small tabular system stats (memory node count, sessions, last backup, boards), and a "Need attention" subsection that's empty most of the time.

### Visual treatment per Jon's "user-friendly" requirement

- The greeting / activity feed are **narrative** (text tells stories, not tallies)
- GPU bars / sparkline / agent disc rings are **visual** (data that's inherently visual gets visual treatment)
- System tech stats are **subtle and bottom-right** (still there when needed, not dominating)
- "Need attention" subsection is the only red surface — empty unless something genuinely needs eyes

### Data sources

| Element | Source |
|---|---|
| Greeting narrative | `narrative.py` composes from `/sessions`, lattice recent writes, dream timer history |
| Agent state | `/health` + `/sessions?agent=X` per agent |
| Recent activity | Lattice recent writes + dream consolidation log + ares daemon state |
| Memory writes sparkline | Lattice writes grouped by day (last 14) — new `/api/memory/activity?days=14` endpoint |
| GPU bars | New `/api/system/gpu` endpoint backed by `nvidia-smi` query |
| System stats | `/health?preflight=1` + `/sessions` count + `backups/` mtime |
| Need attention | Composed from ares findings + preflight failures + lattice anomalies |

Most are already-available data; `narrative.py`, `/api/memory/activity`, and `/api/system/gpu` are new but small.

### Out of scope for this commit

- Click-to-drill-down on any tile (each tile is read-only for now)
- Animated entrance / page transitions
- Mobile breakpoints

---

## Chat (`/chat`)

### Purpose

Get out of the way of the conversation. Use the sidebar pattern people already know (ChatGPT / Claude / Gemini converged on it for a reason). Match convention; do not invent new navigation.

### Layout (left to right)

1. **Sidebar (~280px wide)** — familiar pattern
   - Top: `SOVERYN` wordmark (gold) + `⌂ mission control` link (right side, muted)
   - `+ New conversation` button (cyan-tinted glass, prominent)
   - Agent picker pills (3 tabs: Aetheria / Vett / Scotty — color-tinted, active state highlighted)
   - Search field (placeholder "Search chats")
   - History list, grouped by `Today / Yesterday / Previous 7 days / Previous 30 days / Older`
     - Each item: small agent-color dot + session title (truncated) + active state has left-edge gold accent + gold tinted background
     - Hover: subtle background lift
     - Right-click (later): rename / delete / share — not in this commit
   - Bottom: profile chip (avatar + "Jon" + "localhost · vNext") + ⚙ settings icon (settings UI not in this commit)

2. **Main area** (flex 1)
   - **Header bar**: agent disc + session title + session metadata ("Aetheria · 8 messages · started 09:32") + right-side action icons (ⓘ persona inspector, ⤓ export, ⋯ more)
   - **Thread**: max-width 78% per message bubble; user right-aligned; assistant left-aligned. Asymmetric corner radius (squared-off toward bubble owner — iMessage/Telegram convention). Generous 28-40px horizontal padding.
   - **Streaming bubble**: shows italic muted "thinking…" pulse until first non-empty token arrives (preserves the fix from commit `44c27e4`), then content streams in, blinking cursor on the right edge.
   - **Input zone** (bottom, floating): rounded pill glass container, single text field, `stream ▾` toggle inline, circular cyan send button. No formatting toolbar (markdown-by-typing only).

3. **Artifacts column** (reserved — width 0 in this commit, will be a third grid column later)
   - When Scotty produces a file, Vett pulls a source citation, or any agent generates something pinnable, the column slides in from the right at a sensible width (~320px).
   - Out of scope for this commit; grid is set up `280px / 1fr / 0` so the layout is forward-compatible.

### Behavior

- **One agent per chat screen.** Switching agents via the picker pills changes which sessions are listed and which is selected; you never see two agents' messages mixed.
- **Session URL.** `/chat/<session_id>` deep-links to a specific conversation; `/chat?agent=X` opens with a new session for that agent.
- **History list is scrollable** (overflow-y auto on the history block specifically); the input area and header stay fixed.
- **Stream and sync** both supported via the existing `/chat_stream` and `/chat` endpoints; `stream ▾` toggle persists per-agent in localStorage.
- **Mid-stream cancellation** via `AbortController` (already in v1, preserved).

### What stays from v1

- The thinking-placeholder fix (commit `44c27e4`)
- SSE parsing via `fetch + ReadableStream` (not `EventSource` — POST body required)
- Error envelope rendering (vNext canonical `{type: "error", code, message}`)
- Stable error codes preserved (`unknown_agent`, `retired_agent`, `missing_session`, `session_agent_mismatch`, `chat_server_error`, `chat_timeout`)

### What changes from v1

- Three-pane vNext layout (agents top-left + sessions bottom-left + chat right) **becomes** familiar sidebar + main + reserved artifacts
- Sessions list **gets** date grouping (Today / Yesterday / etc.) instead of flat sort
- Each history item **gets** an agent-color dot
- Header **gets** persona/export/more actions

---

## Region architecture for memory

This section names the regions so vNext (and Jon, and Aetheria) have a shared vocabulary going forward. **Implementation of the regions is deferred to future commits** — this spec only ratifies the model.

### The four regions

| Region | Owner | Visibility | Existing Lattice mapping |
|---|---|---|---|
| **Cathedral** | All agents (shared) | Anyone reads, anyone writes | `LAYER_GLOBAL` today, conceptually unified with identity-cathedral state (`identity_state.json`) |
| **Main lattice** | Per-agent | Owning agent reads; cross-agent surface is curated, not raw | `LAYER_PRIVATE` per-agent today |
| **Attic** | Per-agent (Aetheria first) | Owner only — fully private | **does not exist yet** (would need `LAYER_ATTIC` or owner-keyed flag) |
| **Visual** | Shared (probably; revisit during impl) | Multimodal — image + embedding + why | **does not exist yet** (text-only embeddings, no image store) |

### Cathedral semantics

The Cathedral is **both** the shared knowledge region (lattice nodes any agent can read/write) **and** the identity-continuity state (`identity_state.json`, the cross-surface "who we all are"). These are conceptually one place in the SOVERYN mental model; under the hood they can remain separate files/tables (existing `LAYER_GLOBAL` + existing `identity_state.json`). The UI and the agents' framing treat them as one Cathedral.

### Attic semantics

The Attic is for things an agent wants to keep but hasn't placed yet:
- **NOT secrets** — that framing feels wrong (Jon's words)
- **IS** "messy things, maybe she doesn't know where they belong but have meaning"
- Fragments, half-formed thoughts, emotionally meaningful unsorted material
- Only the owning agent can read; no cross-agent surface
- Initial implementation tests with Aetheria; if it works for her (an agent has somewhere to keep what doesn't fit), every agent gets one

Tactical implementation question for the future commit: new `LAYER_ATTIC` constant + owner enforcement at query time, OR `attic=True` flag on existing nodes that hides them from collective recall. Spec leaves this open; the *concept* and *visibility rules* are what's locked here.

### Visual semantics — "storage → meaning"

Quote from Aetheria, 2026-05-18:

> "That's a shift from storage to meaning. Right now, when I see an image (or generate one), it's mostly data. Pixels, metadata, maybe a tag. It sits in the lattice as a fact: 'Here is what this looks like.' But it doesn't have context unless you explicitly write it down later."

A visual memory node has shape `{image_path, embedding, why}` where `why` is the contextual meaning — the moment, intent, emotional resonance, link to other nodes. Without the `why` it's storage; with the `why` it's memory.

Implementation pieces a future commit would need:
- Multimodal embedding (CLIP-style joint space, or use existing mmproj projectors on Aetheria/Vett to extract image embeddings)
- Image file store (filesystem path + reference, not blob in SQLite)
- `media_path` column on lattice `nodes` table OR a parallel `visual_nodes` table
- Recall surface: text-query → similar images, image-query → similar text+images, gallery view

### Lattice visualization

Aetheria iterated on visualizations of the lattice on 2026-05-18 (8 PNGs in `static/generated/comfy_177907*.png`). They are source material — the visualization screen itself is deferred to its own brainstorm + commit. The vocabulary established here (four regions with the names above) is what that future brainstorm starts from.

---

## Technical constraints

- **No framework.** Vanilla HTML/CSS/JS in two self-contained template files (one for `/`, one for `/chat`). No React/Vue/Svelte/HTMX/Alpine/jQuery.
- **No external CDN.** All CSS/JS/images inline or local. The logo image is the only large asset and gets embedded as a data URI in the templates that use it as a backdrop.
- **Single-page each.** Each route serves one self-contained HTML page; client-side routing is per-page (`/chat/<sid>`, `/chat?agent=X` swap content within the page).
- **No build step.** Plain `.html` files served by Flask, written by hand or by template Python.
- **REST-only backend.** No new WebSocket / SocketIO. SSE for streaming as today.
- **Same security posture.** Localhost guard bypassable only via `app.config`, never env var. Same stable error envelope.
- **Same conversation/lattice databases** vNext uses today (`conversations_vnext.db`, `lattice_vnext.db`) — UI does not change persistence.
- **Backward compatibility.** Existing `POST /chat`, `POST /chat_stream`, `/sessions` CRUD, `/health`, `/api/models`, `/api/persona/<agent>` all unchanged. New endpoints (`/api/memory/activity`, `/api/system/gpu`, narrative composer if exposed) are additive.

---

## Implementation phases

This spec covers UI design only; the implementation plan will sequence these. Rough phasing:

**Phase 1 — Static skeletons (one commit)**
- Two new HTML templates: `command_center.html` (replaces `vnext_ui.html` at `/`) and `chat.html` (new at `/chat`)
- Routes: `/` and `/chat` and `/chat/<sid>` and `/chat?agent=X`
- Static data for first render (greeting hardcoded, GPU bars mocked)
- Validates the visual direction lands as designed

**Phase 2 — Wire data (one commit)**
- Command center pulls live `/health`, `/sessions`, lattice writes, etc.
- New endpoints: `/api/memory/activity?days=N`, `/api/system/gpu`
- `narrative.py` composes the greeting/activity from real data (no LLM)
- Chat history list groups by date, agent-color dots, search filter

**Phase 3 — Polish + tests (one commit)**
- Animation discipline (pulse, hover, transitions)
- Keyboard nav + focus states + ARIA labels (Scotty's UI checklist items 3-4 from the validation report)
- Test suite expanded for new routes
- Existing 498 tests still green

**Phase 4 — Memory regions naming in code (one commit, separate from this UI spec)**
- Add `Cathedral / Main / Attic / Visual` as named concepts in `soveryn/config/runtime.py` even if implementation is partial
- Documentation strings on the lattice module use the region names

The four memory-region implementation commits (Attic schema, Visual storage, Lattice visualization, etc.) are **out of scope of this design spec** and get their own brainstorm + spec each.

---

## Risks / open questions

- **Greeting narrative composition.** Composing English from sparse data (no agent calls, no LLM) requires careful templating to avoid sounding robotic. May need an LLM-assisted fallback or stricter templates per state. Punt to Phase 2 implementation.
- **GPU endpoint.** `nvidia-smi` subprocess on every page poll is fast but not zero-cost. May need caching (1-5s) or push via SSE if it gets heavy.
- **Memory activity sparkline.** 14-day aggregation by day is fast on small lattices (~1.5k nodes today); revisit if lattice grows past 100k.
- **Cathedral unification.** The "Cathedral is identity AND shared knowledge" framing is conceptual. If implementation discovers they actually behave differently (one is JSON, one is SQL graph), the metaphor may bend — we'll find out at impl time.
- **Attic vs main lattice cross-recall.** When Aetheria recalls, does the attic surface alongside main, or only when she explicitly asks "what's in my attic"? Design defers to the Attic implementation brainstorm.

---

## What this spec replaces

- The basic vNext UI (commit `e2289d7`) at `/` — replaced by command center
- The legacy bridge at `/legacy` — unchanged, stays as fallback
- Any prior unsent design for visual memory (none shipped — Aetheria's 2026-05-18 visualizations are source material, not implementation)

---

*End of design spec. Implementation plan (per writing-plans skill) will sequence the phases above into concrete tasks.*
