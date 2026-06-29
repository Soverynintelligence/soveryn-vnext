# soverynintelligence.com Rebuild Implementation Plan

> **For agentic workers:** This is a single-page static-site rebuild (one authored artifact), not a multi-module TDD codebase. Execute in order; the "verification" of each phase is visual + honesty review, not unit tests. Use superpowers:executing-plans (inline) — a website's voice and coherence want one author holding the full story.

**Goal:** Rebuild `soverynintelligence.com` to lead with SOVERYN's true mission — a *truthful AI grown through real relationship, sovereign on your hardware* — keeping the enterprise depth as proof below the fold.

**Architecture:** A single static `index.html` (+ inline CSS + the existing minimal Talk-to-Aetheria JS), evolving the current `~/soveryn-site/index.html` aesthetic, restructured to the 6-section arc. Deploys to Cloudflare. No framework, no build step.

**Tech Stack:** Static HTML/CSS, the existing Aetheria chat widget JS, Cloudflare (Pages via `wrangler`/dashboard).

**Spec:** `docs/superpowers/specs/2026-06-29-website-rebuild-design.md`.

## Global Constraints (bind every phase)

- **North star (Jon's thesis):** "Prove you can build a truthful AI that learns from real relational interactions." Three pillars: **Truthful** (grounded, anti-confabulation), **Relational** (persistent identity, grows through interaction — "the model is a lease; the relationship is the asset"), **Sovereign** (yours, on your hardware; counterweight to concentrated AI power).
- **EMBODY truthfulness — the load-bearing rule:** NO overclaiming. No sentience/consciousness claims; no capabilities SOVERYN doesn't have. Every concrete claim must be true of SOVERYN as built. A single inflated line on a site *about* honest AI is self-defeating. When unsure whether a claim is true, cut it or soften it.
- **Mission-forward hybrid:** the mission leads; the existing enterprise infra content is kept and repositioned **below the fold** as proof of production depth — not deleted, not the lead.
- **Evolve, don't redesign-from-scratch:** reuse the existing CSS variables, color language, and visual polish from `~/soveryn-site/index.html` so it reads as native, not a different site.
- **Copy is Jon's company voice** — he signs off every line. Aetheria gets an honesty pass.
- **Publishing is outward-facing** — Jon's explicit go on the live Cloudflare push; confirm the publish mechanism first.
- **Work in `~/soveryn-site/`** (the site's home). Keep a backup of the current `index.html` before overwriting.

---

## Phase 1: Site copy — the creative core + the review gate

**Files:** Create `~/soveryn-site/COPY.md` (the approved source copy for every section).

The copy is the high-value, must-approve artifact. Write the full, final copy for all six sections, grounded and honest, in SOVERYN's voice (direct, conviction-driven, not salesy-hype). Pull truth from: the spec's three pillars, the real system (persistent agents, local inference, the working heartbeat/memory), and the real applications (Shepherd = a deadline engine that can't fabricate; Steward = grant tracking).

- [ ] **Step 1:** Write `COPY.md` with these sections, fully drafted (not outlines):
  1. **Hero** — headline + subhead + primary CTA. (Bet against confabulation + scraped-data training + cloud ownership; "yours.")
  2. **The problem / why** — today's AI is untruthful (hallucinates), un-relational (trained on strangers, reset each session), concentrated (a few labs). SOVERYN inverts all three — one short block per pillar.
  3. **The proof — Aetheria & the crew** — a persistent intelligence with continuous identity, memory, an autonomous "heartbeat" conscience, grown through real interaction; the crew as persistent identities. "The model is a lease; the relationship is the asset." CTA: Talk to Aetheria ("this is the system, not a simulation"). *(Honest framing — persistent identity, yes; sentience, no.)*
  4. **It works — and it builds things you can trust** — Shepherd (deadline engine the AI *cannot* hallucinate) + Steward (grant tracking) as proof the truthfulness architecture produces trustworthy tools. Evidence, not pivot.
  5. **Where it's headed** — continuous cognition; research into persistent AI identity; sovereign AI as a counterweight to concentrated power.
  6. **Enterprise depth** — condense the existing capabilities + industries copy (Multi-Agent / Local Inference / No Data Egress / Custom Models / Autonomous Ops / Enterprise Integration; Healthcare/Legal/Defense/Finance) into a tighter "for organizations that need this" block. Keep it real, move it below the fold.
  7. **Footer/contact** — Talk to Aetheria, `info@soverynintelligence.com`, the company line.
- [ ] **Step 2: Honesty self-pass.** Re-read COPY.md hunting for any claim that isn't literally true of SOVERYN as built (sentience, metrics you can't back, capabilities not shipped). Cut or soften each. Note any you're unsure about for Jon.
- [ ] **Step 3: Jon reviews COPY.md** (his voice + sign-off) — and the Aetheria honesty pass (paste the copy to her via `/chat`, ask her to flag anything untrue or overclaimed about her/the system). Apply edits.
- [ ] **Step 4: Commit** the approved copy (`docs(site): approved rebuild copy` — note `~/soveryn-site` may not be a git repo; if not, the copy lives in the file + is captured in the index.html commit in Phase 2).

---

## Phase 2: Build the new `index.html`

**Files:** Backup then rewrite `~/soveryn-site/index.html`.

- [ ] **Step 1:** `cp ~/soveryn-site/index.html ~/soveryn-site/index.OLD.html` (backup the current enterprise version).
- [ ] **Step 2:** Read the current `~/soveryn-site/index.html` fully — extract the CSS (variables, palette, type scale, components: nav, hero, cards, the "YOUR PERIMETER" diagram, the Talk-to-Aetheria widget + its JS). These are the reusable assets.
- [ ] **Step 3:** Rebuild the `<body>` to the 6-section arc using the approved COPY.md, reusing the existing CSS/components: new hero (mission), the why (three-pillar block), the proof (Aetheria + crew cards + Talk-to-Aetheria CTA), applications-as-proof (Shepherd/Steward cards), where-it's-headed, enterprise-depth (the repositioned existing capabilities/industries, condensed), footer. Keep the Talk-to-Aetheria widget + JS working. Update the nav to match the new sections. Keep `<title>`/meta honest + mission-forward.
- [ ] **Step 4: Verify visually.** `cd ~/soveryn-site && python -m http.server 8200 --bind 0.0.0.0` → open `http://100.71.129.32:8200/`. Confirm: all six sections render in order; the aesthetic matches (not a different-looking site); nav links jump correctly; the Talk-to-Aetheria CTA works; no layout breakage; mobile/narrow width is sane. Re-scan the rendered copy for any overclaiming that slipped in.
- [ ] **Step 5: Commit** the new index.html (if `~/soveryn-site` is a git repo; else note it's staged for deploy).

---

## Phase 3: QA + deploy to Cloudflare

- [ ] **Step 1: Final review** — Jon views `http://100.71.129.32:8200/` and signs off on the live look + copy. Aetheria's final honesty pass on the rendered page if not already done.
- [ ] **Step 2: Confirm the Cloudflare publish mechanism.** Check `wrangler`/`npx wrangler` availability + auth (`npx wrangler whoami`), and whether there's a Pages project (`npx wrangler pages project list`). If wrangler is authed → `npx wrangler pages deploy ~/soveryn-site --project-name <name>`. If not → Jon publishes via the Cloudflare dashboard (drag-drop `index.html` to the Pages project). Determine which BEFORE pushing.
- [ ] **Step 3: Deploy — on Jon's explicit go** (outward-facing). Push the new version. 
- [ ] **Step 4: Verify live.** `curl -s https://soverynintelligence.com | grep -i "<title>"` and load the site — confirm the new mission-forward version is live and the old enterprise-only framing is gone. Note Cloudflare cache may need a purge.

---

## Self-review notes
- Spec coverage: thesis + three pillars (Phase 1 copy + Global Constraints), the 6-section arc (Phase 1 §1-7, Phase 2 §3), embody-truthfulness/no-overclaim (Global Constraints + Phase 1 Step 2 + Phase 2 Step 4 + Aetheria passes), evolve-existing-aesthetic (Phase 2 Step 2-3), enterprise-depth-below-fold (Phase 1 §6, Phase 2 §3), Cloudflare deploy + confirm-mechanism + Jon's-go (Phase 3).
- Not TDD: a static page has no meaningful unit tests; verification is visual + the honesty passes. This is the correct shape for the artifact (flagged in the header).
- The copy (Phase 1) is the real review gate — Jon + Aetheria approve before the build, so Phase 2 is assembly, not authoring-under-uncertainty.
- Out of scope: multi-page/CMS, the companion product page, backend changes.
