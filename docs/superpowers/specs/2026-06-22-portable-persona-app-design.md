# Portable Persona App — Design (Slice 1)

**Date:** 2026-06-22
**Status:** Approved design (brainstormed + endorsed). Slice 1 of a multi-slice product.
**Concept:** "Portable Persona" — the **Soul (persona + Lattice memory) as an owned, portable, inspectable asset that rides any engine** (local or cloud). Intelligence is a commodity (swappable brain); identity is the asset (owned bundle).
**Prior exploration:** memory `project_soveryn_mass_market_companion` (market/competitive landscape, swappable-seam proof, Soul-as-moat finding, engine-not-Aetheria reframe).

## Purpose & wedge

A desktop companion that is **truly yours and rides any brain**: you converse, it grows a Sense-of-Us *locally*, and you can flip its brain between a local model and a cloud model (your own key) — your memory never leaving your disk. That single loop *is* portable persona, and it's the smallest sellable slice.

The market gap (validated): companions have memory+identity but are cloud-locked (no privacy); local tools are private but have no identity; second brains have memory but no relationship. Nobody owns memory + local-first + identity + continuous cognition. This does.

## Scope

**Slice 1 (this spec):** desktop home node + the companion loop (converse, local memory, swappable brain, the portable `.soul` bundle, archetype-seed onboarding). Built with a clean **remote-access seam** so the phone is a later slice, not a rewrite.

**Out of scope (later slices / YAGNI):** the phone thin-client ("call home"); cross-device sync beyond the home-node seam; monetization tiers; the *full* continuous-cognition deep loop (MVP ships a light version); a cross-vendor open `.soul` standard; a character/archetype marketplace.

## Architecture — consumer shell over an extracted engine core

Two layers, clean seam.

**Engine core** (lifted from proven/tested code — *this is the product*):
1. **Persona container** — the portable Soul bundle (below). The asset.
2. **Lattice** — per-user local SQLite memory (lifted from vnext): conversations + reflection memories + cognition region.
3. **Swappable inference** — the proven seam (base_url + BYO-key): brain = local model or cloud open-model, config-selected. Only the transient slice ever leaves.
4. **Cognition** — the worth-keeping gate (already built) + the Sense-of-Us note that shapes replies and grows over time. MVP ships a *light* growth loop; the full continuous-cognition loop is the upgrade (perfected separately on the Spark build).

**Consumer shell** (new, lean, for non-technical humans):
5. **App UI** — converse; see/edit your persona; **flip the brain** (🔒 local / ⚡ cloud) with a per-turn indicator; onboarding (pick an archetype, name it, drop a BYO-key).
6. **Home-node service** — runs the engine, owns the bundle on disk, exposes a local API **with a remote-access seam** for the future phone client.

One desktop install: shell ↔ home-node service ↔ engine + `.soul` bundle on disk. SOVERYN-the-system stays Jon's; this extracts the *engine* and gives it a consumer face.

## The portable persona container (the moat)

The Soul is an owned on-disk directory — a `.soul` bundle:

```
my-companion.soul/
  manifest.json          # format version, persona id, name, seed ref, timestamps
  persona/
    seed.md              # anchored starting temperament — identity/values (NOT auto-rewritten)
    sense_of_us.md       # evolving manner note (bounded, ambient, manner-only)
    sense_of_us.history/ # prior note versions — audit + revert
  memory/
    lattice.db           # the Lattice: conversations, reflection memories, cognition region
  config.json            # brain selection (local model id / cloud endpoint+model) — NO secrets
```

**Moat properties:**
- **Identity is a file** — copy/back-up/move it; export = zip, import = drop in. Competitors trap memory in a cloud account; this is a file you hold.
- **Engine-agnostic** — bundle holds no model/engine, only identity + memory + config. "Lease the brain, own the Soul," literal.
- **Credential-isolated** — BYO-key lives in the OS keychain, NOT in the bundle, so the Soul moves/shares without leaking the key (re-enter key once on a new machine).
- **Inspectable / sovereign** — `seed.md` + `sense_of_us.md` are human-readable markdown (read/edit who your AI thinks you are); Lattice is plain SQLite. No black box.
- **Integrity-railed by construction** — seed anchored; only `sense_of_us.md` evolves; the cognition store's write-isolation means the engine *physically cannot* rewrite the seed. The fence ships inside the container.
- **Versioned** — `manifest.json` carries a format version from day one so bundles migrate as the format evolves.

**MVP portability scope:** "portable across your own machines + our engine" (back up, move to a new PC, restore). True cross-vendor "load my Soul into anyone's app" needs a published open format — north-star, not v1. (Once bundles are proven and users are attached, *we* define that spec.)

## Data flow + the brain-flip

Per turn, memory stays local, brain is swappable:
1. Message → home-node.
2. **Retrieve locally:** relevant Lattice context + `seed.md` + current `sense_of_us.md`. Never transmitted.
3. **Assemble the transient slice:** persona seed (system) + sense-of-us note (ambient, cache-stable) + retrieved snippets relevant to *this* message + the message (~hundreds of tokens, not the corpus).
4. **Send to the selected brain:** local → `127.0.0.1` llama-server (nothing leaves); cloud → open-model endpoint with keychain key (only the slice leaves, to the user's own account, under their terms — we never see it).
5. **Response** → shown → **written back to the local Lattice.**
6. **Background cognition** (idle): reflect over recent turns → gate → grow `sense_of_us.md` (manner only, write-isolated). Runs **local** — the privacy-heaviest step (reads lots of memory) never touches cloud; the cloud brain only ever inherits the *result* in the next slice.

**Brain-flip** = changing which endpoint the seam targets. Same persona + memory + prompt feed either brain → "same her, different engine"; the user feels latency/IQ shifts, not an identity shift (as long as the slice format is normalized across brains). Per-turn indicator: 🔒 local / ⚡ cloud. Toggle global or per-conversation.

**Privacy contract (one line):** your whole mind stays on your disk; only the slice needed to answer this turn travels, and only to a brain you chose.

## Day-one identity

**Archetype picker.** Onboarding offers ~3–4 starting temperaments (e.g. *Direct & Sharp*, *Warm & Encouraging*, *Curious & Playful*, *Calm & Grounded*), each an editable `seed.md`. Then a **"name your companion"** beat — the moment the `.soul` folder becomes a possession, not a chatbot. The Sense-of-Us personalizes from there. The seed is anchored (only manner evolves), so the chosen archetype is the AI's stable identity. **None of the archetypes is Aetheria** — she's the reference implementation; the product ships generic, user-owned seeds.

## Error handling & safety

- Cloud brain down / no key → fall back to local model if present, else a clean "brain unavailable" message. Memory + persona always intact; never blocked.
- Weak/no-GPU machine → cloud is the default brain (the swappable finding makes this viable + cheap).
- Home-node unreachable (future phone slice) → cached recent context + cloud brain, sync when home's back.
- Integrity: seed anchored; manner-only evolution; write-isolation enforced at the store boundary; everything inspectable + revertible (note history).

## Testing

- Engine core lifts its existing tests (Lattice, swappable seam, cognition gate are already covered).
- New shell/home-node tests: onboarding (archetype pick + name + key), the converse loop, brain-flip (local↔cloud, same slice format), **export/import a `.soul` bundle** (round-trip: export → fresh install → import + re-key → continue), local-memory-never-leaves assertion (cloud path sends only the slice), credential-isolation (key never written into the bundle), degradation paths.

## Build approach

**Lift the proven internals into a lean consumer shell** (approach C). Take the battle-tested pieces as a core — Lattice (vnext), swappable-inference seam (spike/swappable-brain), persona/prompt-assembly (vnext), cognition gate + store (feat/continuous-cognition) — and wrap them in a new lean app shell built for consumers. Reuse the engine; do not fork/strip the whole vnext app, and do not greenfield-reimplement the proven pieces.

## Dependencies & open items

- Extracts from: vnext (Lattice, prompt-assembly), spike/swappable-brain (the seam), feat/continuous-cognition (cognition gate + store).
- Open (decide at plan/build time): exact `.soul` manifest schema v1; the 3–4 shipped archetype seeds (content); desktop shell tech (e.g. Tauri/Electron — pick at planning); the light-vs-full cognition loop boundary for MVP.
- Monetization deferred to a later slice; note the model is cheap to run (BYO-key = ~zero inference cost to us), so the business is selling the app/experience, not reselling tokens.
