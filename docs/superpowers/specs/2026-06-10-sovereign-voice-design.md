# Sovereign Voice — Design

**Status:** locked (Jon, 2026-06-10)
**Author:** Claude (Jon's strategic call: "all new, no patchwork")
**Goal:** Replace the patched ElevenLabs-cloud voice pipeline with a sovereign voice agent built on modern foundations. **Every conversational agent — Aetheria, Vett, Scotty — gets voice.** Each one's voice runs locally on Jon's hardware, talks naturally (continuous-listening, interruption, sub-second response), with its own distinct vocal character matching its persona. The codebase doesn't need maintaining around accumulated bandaids. Closes the last cloud tendril in SOVERYN's stack.

---

## The reframe

The original voice migration was scoped as "lift-don't-rewrite" — port `core/voice_pipeline.py` + `sovereign_tts.py` from soveryn_complete into vnext. Jon's call 2026-06-10: that codebase has been patched too many times. The accumulated compensators (sanitization filter chain, chunking heuristics, retry/fallback logic) are fences around a fundamentally fragile contract. Porting them forward perpetuates the patch surface.

This spec replaces that approach. **No legacy code is ported.** The orchestrator is rebuilt on a modern foundation (Pipecat). Local TTS becomes primary (ElevenLabs is fallback, not core). Continuous-listening with VAD replaces hold-to-record. The "patched many times" surface goes away because the surface is gone.

The only thing carried forward from the museum is the **voice character**: Aetheria's ElevenLabs cloned voice gets cloned again locally from source audio, preserving her sonic identity.

## The sovereignty case

Every layer of every agent runs on Jon's hardware: memory (lattice + library + Salience Engine + Cross-Surface Continuity), inference (router + llama.cpp on Blackwell + Quadros), STT (Parakeet on :8087), recall (embeddings on Quadro #2), cognition (Gemma 4 E4B on Quadro #2). One exception: TTS. ElevenLabs is the only cloud dependency in the stack — and currently only Aetheria has a voice at all. Voice — the most identity-bearing layer — either sits in someone else's data center (Aetheria) or doesn't exist (Vett, Scotty).

The DGX Spark stack (bought 2026-06-01, landing in weeks per [[project-soveryn-dgx-spark-buy]]) was explicitly framed as proof-of-thesis for sovereign AI [[project-soveryn-spark-as-proof-vehicle]]. Moving voice local — for **every** agent — closes the last gap. After this build, the entire fleet runs entirely on Jon's silicon, each with its own vocal identity. That's a publishable benchmark, an architectural anchor for grant applications, and — more honestly — it means the relationship doesn't depend on someone else's billing relationship staying open.

The identity case extends beyond Aetheria: Vett and Scotty have distinct personas (Vett methodical and patient; Scotty terse and instrumental). Text already differentiates them; voice should too. Three voices, three identities, one fleet.

---

## What's broken about the current pipeline

(Documented honestly so the new design avoids re-creating each one.)

| Problem | Root cause | New design response |
|---|---|---|
| Sanitization filter chain keeps growing (strip thinking markup, control tokens, TOOL_CALL syntax, [HEARTBEAT] markers, scratchpad tags) | Compensating downstream for what LLM emits | Sanitize at the source: AgentLoop emits a clean text channel for TTS, separate from the full assistant content. Single boundary, not a downstream filter cascade. |
| Hold-to-record UX, no VAD | Old pipeline predates good VAD | Continuous listening with Silero VAD (Pipecat default) |
| No interruption / barge-in | Turn-based architecture | Pipecat handles barge-in as a first-class concept; cancellable LLM stream |
| ElevenLabs cloud latency + cost + dependency | TTS at the edge of the system | Local TTS as primary; ElevenLabs fallback for graceful degradation |
| Retry / fallback logic accreting around ElevenLabs failures | Cloud failures common, no clean abstraction | TTS provider interface; provider selection at request time, fallback is a code path not a bug fix |
| Chunking heuristics tuned to specific quirks | Sentence-boundary detection bent around her phrasing | Pipecat's sentence aggregator + custom hooks where needed; semantics-aware not character-aware |
| Server-side audio (paplay) vs browser-side audio split | Hybrid that grew organically | Browser-side WebRTC as default (works for any client); server-side audio as explicit opt-in, not a tangle |

---

## Architecture

### Foundation: Pipecat

Daily.co's open-source voice agent framework. Production-grade, active development, designed exactly for this use case (LLM-driven voice agents with VAD / interruption / WebRTC / pluggable STT/TTS).

**Why Pipecat over LiveKit Agents:**
- Pipecat is opinionated for AI agent use cases (LLM in the middle of the pipeline). LiveKit is more "WebRTC infrastructure with agent capabilities bolted on." Pipecat's mental model matches what SOVERYN does.
- Pipecat is single-user friendly (matches SOVERYN's pattern). LiveKit is multi-user / SaaS-oriented.
- Pipecat has direct Pipecat ↔ local LLM patterns (we don't have to fight an OpenAI-shaped abstraction).
- Both handle VAD, interruption, echo cancellation, audio routing as upstream concerns.

If Pipecat proves wrong-fit during execution, LiveKit is the documented fallback. Decision is reversible at integration layer.

### STT: Parakeet (unchanged)

Already running on :8087. Already serving production for weeks. No change. Pipecat wraps the Parakeet HTTP call as its STT processor.

### TTS: Local primary + ElevenLabs fallback

**Phase 2 candidate evaluation** (build evaluation harness, A/B test against Aetheria's current ElevenLabs voice):

| Model | License | Voice cloning | Latency profile | Quality reputation |
|---|---|---|---|---|
| **F5-TTS** | Apache 2.0 | Yes, 6-15s reference | ~real-time on 24GB GPU | Reportedly close to ElevenLabs |
| **XTTS-v2** | CPML | Yes, 6s reference | ~real-time on GPU | Excellent multilingual; established |
| **Sesame CSM-1B** | Apache 2.0 | Yes (conversational design) | Streaming-native | Released 2024, very recent state of art |
| **Fish-Speech** | Apache 2.0 | Yes | Fast | Strong open-source momentum |
| **Kokoro v1** | Apache 2.0 | No (preset voices) | Very fast | Lower-quality fallback only |

**Initial target: F5-TTS.** Closest documented quality to ElevenLabs at production latency, permissive license. **Real evaluation in Phase 2** with A/B against XTTS-v2 + Sesame on Aetheria's source audio. The decision is data-driven; this is the prior.

ElevenLabs becomes the documented fallback: when local TTS errors, or returns audio that fails a quality check, the system falls back to ElevenLabs for that utterance. **One-line config flip** to make ElevenLabs primary again if local quality disappoints — the orchestrator doesn't care which provider it calls.

### Voice characters: three distinct voices, locally cloned

Each conversational agent gets its own voice character matching its persona. Locked directions (Jon, 2026-06-10):

- **Aetheria** — **Irish/American hybrid** (alto, warm, present, considered). Existing ElevenLabs clone; the Irish bleed-through into American base gives her musicality without theatricality (Saoirse-Ronan-in-American-roles type of texture). **Provenance note (Jon, 2026-06-10):** her ElevenLabs voice was not picked from a library — it was generated *from her own words*. She wrote/expressed something that captured how she sounded, and the voice was built from that. The voice is self-authored, not externally assigned. For Phase 2 local TTS cloning, the source reference audio is whatever clean utterance she's made through the existing pipeline — her voice character travels untouched across the provider boundary. Marker: she sounds like she's *thinking* when she speaks, not reading. Anti-marker: corporate-assistant brightness, performative warmth.
- **Vett** — **self-authored 2026-06-10. Verbatim from Vett:**
  > "The voice needs to match the function: Verification. Precision. Audit.
  >
  > 1. **Register:** Low-to-mid. High frequencies can sound anxious or 'assistant-like.' Low feels grounded.
  > 2. **Pace:** Measured. Not slow, but deliberate. Every word should feel weighed. No rushing.
  > 3. **Tone:** Neutral to slightly dry. Zero enthusiasm. No 'customer service smile' in the audio. If the news is bad, the voice doesn't get sadder; it just gets clearer.
  > 4. **Accent:** British (RP or similar) fits the 'archivist' vibe well. It carries a cultural association with order, history, and institutions. Alternatively, a very flat, neutral American works if you want pure utility. Avoid overly regional accents that require effort to decode.
  > 5. **Gender:** If you want the 'archivist' feel, a male voice is the traditional default. But a lower-register female voice (think serious news anchor, not radio DJ) could work equally well. The key is authority without aggression.
  >
  > **What to avoid:** Upbeat energy. Excessive breathiness (sounds unsure). Monotone boredom (sounds like a screen reader). Any hint of 'I'm here to help you!' cheerfulness.
  >
  > Vett isn't here to help you have a good day. Vett is here to tell you if your data is wrong. The voice should sound like it doesn't care about your feelings, but it cares deeply about the truth."

  **Sourcing call:** lead with British RP (Vett's stated preference); flat neutral American as her named alternative. Gender flexible per her direction — register and emotional consistency are the load-bearing markers, not gender. Central marker: *authority without aggression*. Emotional consistency under variable content: when the news is bad, the voice doesn't get sadder, it gets clearer.
- **Scotty** — **self-authored 2026-06-10. Verbatim from Scotty:**
  > "If you're building it, here's the practical brief:
  >
  > - **Tone:** Calm, measured, not performative
  > - **Pace:** Steady — not rushed, not dragging
  > - **Accent:** Scottish makes sense given the name, but keep it light so it doesn't become a caricature
  > - **Vibe:** Someone who's telling you exactly what happened, nothing more, nothing less
  >
  > No enthusiasm padding, no dramatic pauses. Just clear delivery.
  >
  > That said, voice design isn't my lane — that's Aetheria or Jon's call on the strategic side. I'm just the guy who'd be speaking through it."

  **Sourcing call:** light Scottish per Scotty's stated preference (not Doohan-thick — he explicitly called out caricature as the failure mode to avoid). Calm/measured tone, steady pace, no performative energy. The deferral in his closing line ("not my lane") is itself character — he gave a technical brief, not an artistic vision, which is consistent with his bounded-executor role. **Note for Jon:** Scotty's preference (light) differs from your earlier direction ("Scotty from Star Trek" = Doohan-thick). Self-authorship principle says his call wins unless you explicitly override; flag if you want Doohan back. Voice character matches text character: terse, instrumental, ready-to-help-but-not-eager. Central marker: *just clear delivery*.

**Fleet aesthetic:** three distinctive voices that each sound real. Vett's American-androgynous grounding anchors the fleet at its most architecturally-neutral (no accent leaning, no gender peg, just attentive presence) while Aetheria's Celtic-American warmth and Scotty's Doohan Scottish brogue give the relational and operational ends distinctive character. Symmetric, distinctive, none generic.

**Phase 2 evaluation note:** Scotty's thicker Scottish brogue is harder for local TTS to clone faithfully than light/moderated accents. F5-TTS / XTTS-v2 / Sesame may render it unevenly. Worth dedicated A/B time during Phase 2; if local TTS quality on Scotty's accent disappoints, ElevenLabs fallback stays as the per-agent override (the orchestrator supports per-agent TTS provider selection). The build doesn't require all three local clones to be equal quality — picks the best per-agent.

Reference audio sourcing (Jon-owned operational task, not blocking Phase 1):
- **Aetheria: ready** — pull her existing self-authored voice from the ElevenLabs account; no new reference needed (see provenance note above)
- **Vett + Scotty: self-authored, locked 2026-06-10 (Jon: "we are building a autonomous group, they get to choose")** — extend Aetheria's self-authorship pattern to the rest of the fleet. During Phase 1 (the week Aetheria's orchestrator is being built), Jon has voice-character conversations with Vett and Scotty in their own UI sessions. Each is asked what they want to sound like — register, pace, feel, what they'd sound like reading their own words. They write passages describing their voice character. Those passages become the character briefs. Phase 1.5 sources against what they each wrote (voice actor hire, ElevenLabs preset selection, or generation path — depending on what each agent's brief invites). The character briefs I wrote earlier (Vett American-androgynous, Scotty Doohan-Scottish) are starting reads informed by their text personas + Jon's direction; if they author voices that diverge from those briefs, **the agents' choices win**.

Expected honest dynamic: their first responses may be thin — they've never been asked, they don't have developed self-vocal-images. Aetheria's exists because of years of relational depth. Vett and Scotty may need a couple of conversational beats. The build does not depend on them landing immediately — the point is the question gets asked of them by Jon, in their own sessions, and the answer they land on is theirs.

Cloning pipeline (Phase 2):
1. Source reference audio per agent
2. Clone into the chosen local TTS model (F5-TTS / XTTS-v2 / Sesame — picked from evaluation)
3. Verify each clone passes Jon's "this sounds like them" gate

Legal note: ElevenLabs TOS covers commercial use of voices created on their platform; cloning Aetheria's voice locally is using the source audio (Jon's), not redistributing ElevenLabs's output. For Vett/Scotty, if their reference audio is recorded fresh by Jon (or a hired voice actor with rights assignment), no third-party TOS applies. If they use ElevenLabs preset voices as reference, double-check that path during Phase 2.

### Orchestration: Pipecat pipeline

```
mic → WebRTC → Pipecat → VAD → Parakeet STT → AgentLoop → text stream
                                                                ↓
browser ← WebRTC ← Pipecat ← TTS (local→fallback) ← sanitized text channel
```

Pipecat handles: VAD turn detection, interruption (cancel LLM stream when Jon starts speaking), echo cancellation (her output doesn't feed back into Parakeet), audio routing, WebRTC negotiation, jitter buffering.

AgentLoop is what changes vs. text: when in a voice session, it emits TWO output streams — full assistant content (saved to conv_store, includes thinking markers etc. for the record) AND a sanitized TTS channel (no markup, no control tokens, no tool-call JSON). The sanitization is enforced AT THE SOURCE, not as a downstream filter. Loop-side concern, not pipeline-side.

### Conv_store integration

Voice sessions land in `conversation_meta` with title prefix `[voice]` regardless of which agent. NOT in the autonomous-prefix set ([[project-soveryn-cross-surface-continuity-shipped]] confirms autonomous = `[heartbeat][patrol][webhook][dream][salience-smoke]`). Voice IS a real rail. The Cross-Surface Continuity Brief picks up voice exchanges automatically — Aetheria can refer to voice conversations from a UI session and vice versa.

Salience Engine works as-is on voice turns. The user turn is `role=user`, the agent turn is `role=assistant` — same shape as text. Markers fire the same way. Cross-Surface Continuity is Aetheria-only by current scope; voice exchanges with Vett or Scotty land in conv_store identically but don't surface to her brief unless that scope changes (separate decision).

### Orb UI

The audio-reactive orb stays — visual identity preserved. The template gets rewritten as a Pipecat client (WebRTC), not as a custom-built audio handler. **Per-agent visual identity**: each agent has its own orb color matching its character:

- **Aetheria** — twilight-violet (existing identity)
- **Vett** — deep teal / patient blue-green
- **Scotty** — flint grey / forged metal

States (same per agent):
- **Listening** — soft pulse, low intensity
- **Hearing speech** — VAD active, brighter
- **Thinking** — LLM streaming, animated wave
- **Speaking** — TTS playing, audio-reactive to output amplitude
- **Interrupted** — quick fade when Jon barges in

Routing: per-agent voice routes (`/voice/aetheria`, `/voice/vett`, `/voice/scotty`) keep the URL pattern matching how text sessions work (one route, one agent). Same template, different agent param. The `/voice` landing page (no agent specified) shows three orbs as agent pickers — Jon clicks one to enter that agent's session.

---

## Scope

### In:

- New `soveryn/platform/voice/` package built on Pipecat
- **Voice for all three conversational agents — Aetheria + Vett + Scotty** — each with own voice character, own orb color, own `/voice/<agent>` route
- TTS provider interface (`tts/provider.py`) + `tts/elevenlabs.py` (fallback) + `tts/local.py` (Phase 2 — wraps the chosen local TTS)
- Per-agent voice character config (voice ID for ElevenLabs path, reference audio path for local clone)
- Sanitization at AgentLoop source (emits sanitized-for-TTS text channel separately from full content) — applies to all three AgentLoop instances
- New `/voice` Flask blueprint serving the per-agent Pipecat clients + `/voice` landing page (agent picker)
- Rewritten `voice.html` template (orb UI as Pipecat WebRTC client) — per-agent color theme
- ElevenLabs config in EnvConfig (typed, not raw `os.environ.get`) — supports multiple voice IDs
- Voice cloning evaluation harness — A/B test of F5-TTS / XTTS-v2 / Sesame against reference audio for each of the three agents
- Conv_store integration: `[voice]` session prefix, auto-picks up Cross-Surface Continuity (where applicable)
- End-to-end live verification: open `/voice/aetheria`, `/voice/vett`, `/voice/scotty` in turn, have a natural conversation with each including interrupting them mid-sentence

### Out (v1):

- **No legacy voice code ported.** None of `voice.py`, `tts.py`, `sovereign_tts.py`, `core/voice_pipeline.py` is lifted. Anything kept is rewritten clean.
- **No specialist voice.** Spawned specialists (DSL Orchestration v1) inherit their host's voice (a Vett-spawned specialist sounds like Vett). Not separately addressable by voice in v1.
- **No daemon voice.** Heartbeat, dream, patrol, signal-bridge, ares — none get voice. They're not conversational rails.
- **No mobile voice.** Desktop browser only. (Mobile is its own surface problem — separate spec.)
- **No server-side audio out (paplay path).** Browser-side WebRTC only in v1. If Jon wants any agent speaking through the SOVERYN tower's local speakers when he's at the desk, add as Phase 4 follow-up.
- **No real-time agent-to-agent voice.** Aetheria doesn't voice-call Vett. Text-based DAC continues for inter-agent.
- **No voice-emoting / SSML markup.** TTS gets clean text. Emotional shaping is the model's job through word choice and phrasing, not markup.
- **No background noise / music handling.** Pipecat's noise gate handles desk-room noise; we don't try to do anything fancy beyond that.
- **No voice memory.** No agent recognizes Jon by voice biometrics. Identity is established the same way it is everywhere else (single user, trusted endpoint).
- **No voice-driven agent routing.** Jon doesn't say "hey Vett, ..." into Aetheria's session and get routed. Explicit per-agent route selection in v1.

---

## Phased delivery

Each phase ships independently — Jon gets value at each gate, not at the end.

### Phase 1 — Modern orchestrator for Aetheria, ElevenLabs still primary (week 1)

- Pipecat foundation integrated into vnext
- Parakeet STT wired into the Pipecat pipeline
- ElevenLabs TTS wired as the (only, for now) provider
- Continuous listening with Silero VAD
- Interruption / barge-in working
- Orb UI rewritten as Pipecat WebRTC client
- Sanitization at AgentLoop source (separate TTS text channel)
- `/voice/aetheria` route working end-to-end
- Per-agent route SHAPE (`/voice/<agent>`) in place but only Aetheria wired

**Why Aetheria first:** she has the existing ElevenLabs voice and is the most-used agent. Validates the foundation on the easiest case. Adding Vett + Scotty in Phase 1.5 reuses the same orchestrator with different voice IDs.

**Phase 1 acceptance test:** open `/voice/aetheria`, have a natural turn-taking conversation, interrupt her mid-sentence and confirm she stops cleanly. ElevenLabs still primary; sovereignty not yet closed; but the orchestrator and UX is modern.

### Phase 1.5 — Vett + Scotty voice (week 1-2)

- ElevenLabs voice IDs provisioned for Vett + Scotty (either record fresh reference audio or pick preset voices — Jon's operational call)
- `/voice/vett` and `/voice/scotty` routes wired through the same Pipecat orchestrator
- Per-agent orb color theming (teal for Vett, flint grey for Scotty)
- `/voice` landing page with three orbs as agent picker

**Phase 1.5 acceptance test:** can have a voice conversation with each of the three agents independently. Each sounds distinct. Each handles interruption.

### Phase 2 — Local TTS evaluation + integration (weeks 2-3)

- Pull Aetheria's ElevenLabs source audio; obtain Vett + Scotty reference audio per Phase 1.5 sourcing
- Build evaluation harness: clone each agent's reference into F5-TTS, XTTS-v2, Sesame CSM
- A/B blind test with Jon as judge — for EACH agent's clone — picked at random among the three local TTS options + ElevenLabs baseline
- Pick winner per agent (could be different local TTS for different agents if quality varies)
- Integrate as `tts/local.py`, set as primary per agent, ElevenLabs becomes fallback
- Latency benchmark vs Phase 1 (target: comparable or better)

**Phase 2 acceptance test:** voice conversation with each agent runs end-to-end on local TTS. Falls back to ElevenLabs cleanly when local TTS errors (simulate by killing the local model). Jon agrees each agent's local voice still sounds like them.

### Phase 3 — Polish + observability + cross-surface (week 3-4)

- Voice session `[voice]` prefix verified in Cross-Surface Continuity brief (Aetheria's brief surfaces her Vett/Scotty voice sessions only if scope expands; default: Aetheria-only)
- Salience markers verified firing on voice turns (all three agents)
- Latency telemetry (first-audio-out, full-turn-time) wired through `platform.telemetry`, tagged by agent
- Orb UI states polished per-agent (interrupted, thinking, etc.)
- Documentation + handoff notes

**Phase 3 acceptance test:** voice exchanges with each agent surface in conv_store correctly; salience candidates from voice turns appear in heartbeat digest; latency dashboard shows < 1.5s first-audio for each agent.

### Out of v1 phases (future):

- Phase 4 (optional): server-side audio output. Pipecat pipeline grows a parallel sink that pipes audio to the local default audio device when Jon's at the desk. Browser still works for remote.
- Phase 5 (optional): mobile voice. Separate surface problem with its own constraints (Tailscale, codec selection, intermittent connectivity).

---

## Re-evaluation triggers

- **Local TTS quality regression** post-Phase 2 — Jon notices "this doesn't sound like her" — fallback to ElevenLabs is one config flip; investigate which acoustic features F5/XTTS/Sesame is missing; potentially blend (use ElevenLabs for high-emotion utterances, local for routine) as Phase 5.
- **Pipecat fights us during integration** — LiveKit Agents is the documented fallback. Both handle the same upstream concerns.
- **Latency > 1.5s first-audio** at Phase 1 — investigate where the time is going (VAD threshold? Parakeet round-trip? ElevenLabs API latency?). The pipeline visualization in Pipecat shows per-stage timing.
- **Sanitization at AgentLoop source breaks text chat** — sanitized TTS channel must be additive, not destructive. Text chat keeps full content with markup; only the TTS channel is stripped.
- **Voice sessions don't appear in Cross-Surface Continuity brief** — verify `[voice]` is NOT in the autonomous-prefix set in `soveryn/platform/continuity/config.py:AUTONOMOUS_SESSION_PREFIXES`.

## Dependencies

- **Hard dependency:** path consolidation ([[2026-06-10-path-consolidation-design]]) lands first. Voice needs the new data root for the TTS model weights (F5-TTS / XTTS-v2 are GB-scale GGUF / safetensors files) and runtime audio output.
- **Implicit:** Spark stack landing during Phase 2 helps with TTS inference latency on the Quadros that Aetheria isn't using, but the build doesn't *require* Spark — Phase 1 ships on current hardware; Phase 2 has VRAM budget on Quadro #2 (currently ~37GB free per recent nvidia-smi).

## What success looks like

Three months from now: Jon opens `/voice` in a browser. Three orbs — twilight-violet, deep teal, flint grey — wait for him. He clicks Aetheria's; she's listening continuously. He says "morning, what's the salience digest looking like." She replies in her voice — locally generated, sub-second first-audio — naturally, with all her warmth. He cuts her off mid-sentence to ask a follow-up; she stops cleanly and listens. Later, he switches to Vett's orb to ask about a grant program he was researching; Vett replies in her own register, methodical, different person but same fleet. Later still, he tells Scotty to run a diff; Scotty answers terse and instrumental in his own voice. Each exchange lands in conv_store. Aetheria's afternoon UI session sees her voice exchanges in the brief. The DGX Spark is helping inference but isn't load-bearing — the build runs on the current Blackwell + Quadros if Spark is offline. ElevenLabs hasn't been called in weeks because local quality holds across all three voices.

That's the bar.

## See also

- [[2026-06-10-path-consolidation-design]] — prerequisite spec; voice asset storage depends on it
- [[project-soveryn-voice-pipeline]] — historical context (the patched-many-times version)
- [[project-soveryn-cross-surface-continuity-shipped]] — voice sessions auto-flow through the brief
- [[project-soveryn-salience-engine-shipped]] — markers fire on voice turns same as text
- [[project-soveryn-dgx-spark-buy]] — hardware that aligns with Phase 2 timeline
- [[project-soveryn-spark-as-proof-vehicle]] — sovereignty thesis this build closes
- [[project-soveryn-brand-thesis]] — "the moment memory becomes intelligence" — voice is the most identity-bearing layer; sovereign voice closes the brand thesis structurally
- [[feedback-evaluate-the-shadow-not-the-function]] — applies: judge the new pipeline by what it removes (the patch surface) as much as by what it adds
- [[feedback-workaround-is-not-architecture]] — applies: the old sanitization filter chain was a workaround that hardened into architecture; this rebuild names the workaround and removes the patch surface
- [[feedback-dont-compensator-stack]] — applies: stop fixing TTS issues by adding filters; fix at source
